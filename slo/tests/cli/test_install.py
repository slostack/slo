"""Unit tests for ``install.sh`` — the self-bootstrapping installer.

Each test sources ``install.sh`` in a bash subprocess with a stubbed ``PATH`` so the
installer's decision points are exercised without mutating the host (no real
brew / pyenv / pipx / git / network). Fake executables log their invocations to a
call log the tests assert on. ``install.sh`` only runs ``main`` when executed
directly, so sourcing it exposes every function for isolated testing.
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

INSTALL_SH: Path = Path(__file__).resolve().parents[2] / "install.sh"
BASH: str = shutil.which("bash") or "/bin/bash"
ZSH: str | None = shutil.which("zsh")
DASH: str | None = shutil.which("dash")
SH: str | None = shutil.which("sh")

MANAGED_ENV_MARK_BEGIN: str = "# >>> slo managed environment >>>"
MANAGED_ENV_MARK_END: str = "# <<< slo managed environment <<<"
MANAGED_ENV_REL: str = ".slo/shell/environment.sh"
PROFILE_MATRIX: tuple[str, ...] = (".bash_profile", ".bashrc", ".zshenv", ".profile")
CANONICAL_SOURCE_BLOCK: bytes = (
    MANAGED_ENV_MARK_BEGIN.encode() + b"\n"
    b'if [ -r "$HOME/.slo/shell/environment.sh" ]; then\n'
    b'    . "$HOME/.slo/shell/environment.sh"\n'
    b"fi\n" + MANAGED_ENV_MARK_END.encode() + b"\n"
)


def marker_pair_count(*, text: str) -> int:
    """Count complete Slo managed-environment marker pairs in a file's text.

    A complete pair is an end marker appearing after a begin marker; nested or
    unmatched markers therefore count as zero (malformed), matching the
    installer's refusal contract.

    Args:
        text (str): Profile or managed-file content to inspect.

    Returns:
        int: Number of well-ordered begin/end marker pairs.
    """
    count: int = 0
    cursor: int = 0
    while True:
        begin: int = text.find(MANAGED_ENV_MARK_BEGIN, cursor)
        if begin < 0:
            return count
        end: int = text.find(MANAGED_ENV_MARK_END, begin + len(MANAGED_ENV_MARK_BEGIN))
        if end < 0:
            return count
        count += 1
        cursor = end + len(MANAGED_ENV_MARK_END)


def write_fake_pipx_show(*, fake_bin: FakeBin, location: Path | None, pipx_home: Path | None = None) -> None:
    """Install a fake ``pipx`` that records calls and serves deterministic metadata.

    Only the exact ``runpip slo show slo`` invocation answers; the fake exits
    non-zero for any other ``runpip`` argument set so tests drive the
    metadata-parse decision points deterministically.

    Args:
        fake_bin (FakeBin): Per-test fake command harness that owns the write root.
        location (Path | None): Fake distribution Location to report; ``None``
            makes the fake emit no ``Location:`` line.
        pipx_home (Path | None): Fake root returned by the pipx environment API.
    """
    script_lines: list[str] = [
        "#!/bin/sh",
        'echo "pipx $*" >> "$SLO_CALL_LOG"',
        'if [ "$1" = "environment" ] && [ "$2" = "--value" ] && [ "$3" = "PIPX_HOME" ] && [ -z "${4:-}" ]; then',
        f'  printf "%s\\n" "{pipx_home}"',
        "  exit 0",
        "fi",
        'if [ "$1" = "runpip" ] && [ "$2" = "slo" ] && [ "$3" = "show" ] && [ "$4" = "slo" ] && [ -z "${5:-}" ]; then',
        '  echo "Name: slo"',
        '  echo "Version: 0.15.0"',
    ]
    if location is not None:
        script_lines.append(f'  echo "Location: {location}"')
    script_lines += [
        "  exit 0",
        "fi",
        'if [ "$1" = "runpip" ]; then',
        "  exit 1",
        "fi",
        "exit 0",
    ]
    path: Path = fake_bin._bin / "pipx"  # noqa: SLF001 - harness-owned write target.
    fake_bin.write_regular_executable(content="\n".join(script_lines) + "\n", path=path)


class FakeBin:
    """A throwaway PATH directory of fake executables that log their invocations.

    Tests opt tools in (present) or leave them out (absent) to drive the
    installer's ``command -v`` branches. ``uname`` is special-cased to echo a
    chosen kernel name so OS detection can be exercised on any host.
    """

    def __init__(self, *, root: Path) -> None:
        """Create the fake bin dir, call log, and an isolated fake HOME.

        The fake HOME deliberately contains a space and an apostrophe so every
        generated path exercises the installer's POSIX quoting path. The real
        tools the installer/shell startup need are regular wrappers in the fake
        bin; everything else is opted in per test. No fake-bin entry is a
        symlink, so a test can never write through a link to a host executable.

        Args:
            root (Path): Temp root for the bin dir, call log, and fake HOME.
        """
        self._root: Path = root
        self._bin: Path = root / "bin"
        self._bin.mkdir(parents=True, exist_ok=True)
        self._home: Path = root / "home with ' spaces"
        self._home.mkdir(parents=True, exist_ok=True)
        self._log: Path = root / "calls.log"
        self._log.write_text("")
        self._os_release: Path | None = None
        for tool in (
            "mkdir", "grep", "python3", "uname", "sync", "touch", "cp", "rm",
            "cmp", "echo", "printf", "sed", "head", "tail", "cut", "wc", "tr",
            "dirname", "readlink", "od", "cat", "chmod", "mktemp", "mv",
        ):
            self._add_passthrough_wrapper(name=tool)

    def write_fake_pipx(self, *, location: Path | None, pipx_home: Path | None = None) -> None:
        """Install the deterministic fake ``pipx`` metadata server.

        Args:
            location (Path | None): Fake distribution Location; ``None`` makes
                the fake emit no ``Location:`` line.
            pipx_home (Path | None): Fake root reported by pipx. Defaults to the test root.
        """
        write_fake_pipx_show(
            fake_bin=self,
            location=location,
            pipx_home=pipx_home or (self._root / "pipx-home"),
        )

    def make_launcher_layout(self, *, pipx_home: Path | None = None) -> tuple[Path, Path, Path, Path]:
        """Create a validated pipx venv with generated Slo launchers.

        Args:
            pipx_home (Path | None): Optional root to model a platform-specific pipx location.

        Returns:
            tuple[Path, Path, Path, Path]: Venv root, Python, user launcher, and entry launcher.
        """
        root: Path = pipx_home or (self._root / "pipx-home")
        venv_root: Path = root / "venvs" / "slo"
        bin_dir: Path = venv_root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        python_bin: Path = bin_dir / "python"
        quoted_venv_root: str = str(venv_root).replace("'", "'\\\"'\\\"'")
        python_bin.write_text(f"#!/bin/sh\nprintf '%s\\n' '{quoted_venv_root}'\n")
        python_bin.chmod(0o755)
        user_launcher: Path = bin_dir / "slo"
        entry_launcher: Path = bin_dir / "slo-entry"
        generated: str = (
            f"#!{python_bin}\n"
            "# -*- coding: utf-8 -*-\n"
            "import re\n"
            "import sys\n"
            "from src.cli import main\n\n"
            "if __name__ == '__main__':\n"
            "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
            "    sys.exit(main())\n"
        )
        python_bin.write_text(f"#!/bin/sh\nprintf '%s\\n' '{quoted_venv_root}'\n")
        python_bin.chmod(0o755)
        user_launcher.write_text(generated)
        entry_launcher.write_text(generated)
        user_launcher.chmod(0o755)
        entry_launcher.chmod(0o755)
        return venv_root, python_bin, user_launcher, entry_launcher

    def make_package_location(self, *, name: str = "site-packages", index: bool = True) -> Path:
        """Create a fake pipx distribution location with a vendored skills tree.

        Args:
            name (str): Directory name to create under the root.
            index (bool): Whether ``skills/INDEX.md`` is a real file. Pass
                ``False`` to simulate a wheel missing the populated-tree marker.

        Returns:
            Path: The fake distribution location (the value pip metadata would
                report as ``Location:``).
        """
        location: Path = self._root / name
        skills_dir: Path = location / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        if index:
            (skills_dir / "INDEX.md").write_text("# skill index\n")
        return location

    def run_shell_env(
        self,
        *,
        args: list[str],
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a real shell against the isolated roots without sourcing install.sh.

        WHAT: Executes ``bash``/``zsh`` with the given args under the FakeBin
            PATH and isolated HOME/XDG/PIPX/PYENV roots, with the runtime
            variables under test (``SLO_HOME``/``SLO_SKILLS_DIR``) scrubbed
            unless explicitly supplied.
        WHO: Fresh-shell startup tests (login / interactive / POSIX modes) that
            must observe what a real new shell inherits from the profiles the
            installer reconciled.

        Args:
            args (list[str]): Shell executable plus its arguments.
            stdin (str | None): Optional stdin script (used for ``bash -i``).
            env (dict[str, str] | None): Extra environment overrides.

        Returns:
            subprocess.CompletedProcess[str]: The completed shell process.
        """
        full_env: dict[str, str] = self._isolated_env()
        if env:
            full_env.update(env)
        return subprocess.run(
            args,
            input=stdin,
            capture_output=True,
            text=True,
            env=full_env,
            timeout=60,
        )

    @property
    def home(self) -> Path:
        """Return the isolated fake HOME (contains a space and an apostrophe).

        Returns:
            Path: The fake HOME path.
        """
        return self._home

    @property
    def managed_env_file(self) -> Path:
        """Return the canonical managed environment file path for this fake HOME.

        Returns:
            Path: ``$HOME/.slo/shell/environment.sh``.
        """
        return self._home / MANAGED_ENV_REL

    @property
    def profile_paths(self) -> dict[str, Path]:
        """Return the supported shell startup file paths under the fake HOME.

        Returns:
            dict[str, Path]: ``{name: absolute path}`` for ``.bash_profile``,
                ``.bashrc``, ``.zshenv``, and ``.profile``.
        """
        return {name: self._home / name for name in PROFILE_MATRIX}

    def _assert_path_is_within_root(self, *, path: Path) -> None:
        """Reject a fake-bin path whose resolution escapes this fixture's fixed root.

        Args:
            path: Candidate path to validate, resolving existing parents.

        Raises:
            AssertionError: If the path resolves outside this FakeBin's root.
        """
        resolved_path: Path = path.resolve(strict=False)
        resolved_root: Path = self._root.resolve(strict=True)
        assert resolved_path.is_relative_to(resolved_root), (
            f"unsafe fake-bin path {resolved_path}; expected below {resolved_root}"
        )

    def write_regular_executable(self, *, path: Path, content: str) -> None:
        """Replace a fixed-root fake command with a new regular executable.

        Args:
            path: Fake command path below this instance's temp root.
            content: Complete script content for the replacement command.
        """
        self._assert_path_is_within_root(path=path.parent)
        self._assert_path_is_within_root(path=path)
        assert path.parent.is_dir(), f"refusing fake command with missing parent: {path.parent}"
        assert not path.is_symlink(), f"refusing to replace symlink fake command: {path}"
        if path.exists():
            assert path.is_file(), f"refusing to replace non-file fake command: {path}"
            path.unlink()
        path.write_text(content)
        assert path.is_file() and not path.is_symlink()
        path.chmod(0o755)
        self._assert_path_is_within_root(path=path)

    def _add_passthrough_wrapper(self, *, name: str) -> None:
        """Add a temp-local regular wrapper that executes one verified host tool.

        Args:
            name: Host executable name to resolve and expose through the wrapper.
        """
        system_path: str = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        real: str | None = shutil.which(name, path=system_path)
        assert real is not None, f"{name} must exist on the host for the harness"
        self.write_regular_executable(
            content=f"#!/bin/sh\nexec {shlex.quote(real)} \"$@\"\n",
            path=self._bin / name,
        )

    def add(self, *, name: str) -> None:
        """Add a fake executable that logs ``<name> <args>`` and exits 0.

        Args:
            name (str): Tool name to make 'present' on PATH.
        """
        path: Path = self._bin / name
        path.write_text(f'#!/bin/sh\necho "{name} $*" >> "$SLO_CALL_LOG"\n')
        path.chmod(0o755)

    def add_uname(self, *, kernel: str) -> None:
        """Add a fake ``uname`` that echoes ``kernel`` (e.g. Darwin / Linux).

        Args:
            kernel (str): Kernel name ``uname -s`` should report.
        """
        path: Path = self._bin / "uname"
        path.write_text(f'#!/bin/sh\necho "{kernel}"\n')
        path.chmod(0o755)

    def add_os_release(self, *, distro: str, id_like: str | None = None) -> None:
        """Write a fake ``os-release`` file and stage it for the next run.

        Args:
            distro (str): Value for the ``ID`` field.
            id_like (str | None): Optional value for ``ID_LIKE``. Defaults to the
                same token as ``distro``.
        """
        path: Path = self._root / "os-release"
        resolved_id_like: str = id_like or distro
        path.write_text(f"ID={distro}\nID_LIKE={resolved_id_like}\n")
        self._os_release = path

    def run(self, *, snippet: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """Source ``install.sh`` then run ``snippet`` under the stubbed PATH.

        Args:
            snippet (str): Bash to run after sourcing (e.g. ``slo_ensure_pipx``).
            env (dict[str, str] | None): Extra environment overrides.

        Returns:
            subprocess.CompletedProcess[str]: The completed bash process.
        """
        full_env: dict[str, str] = self._isolated_env()
        if env:
            full_env.update(env)
        if self._os_release is not None and "SLO_OS_RELEASE_FILE" not in full_env:
            full_env["SLO_OS_RELEASE_FILE"] = str(self._os_release)
        script: str = f'source "{INSTALL_SH}"\n{snippet}\n'
        return subprocess.run(
            [BASH, "-c", script],
            capture_output=True,
            text=True,
            env=full_env,
        )

    def _isolated_env(self) -> dict[str, str]:
        """Build the fully isolated base environment for one unit subprocess.

        Every writable root a shell-startup path might touch is tmp-owned:
        HOME, the XDG roots, the pipx roots, the pyenv root, and the
        os-release file. ``SLO_HOME``/``SLO_SKILLS_DIR`` are deliberately
        absent so tests control source-time overrides explicitly. All other
        host variables are scrubbed so nothing leaks from the dev machine.

        Returns:
            dict[str, str]: The base environment for subprocesses.
        """
        base: dict[str, str] = {
            "PATH": str(self._bin),
            "HOME": str(self._home),
            "SLO_CALL_LOG": str(self._log),
            "SHELL": BASH,
            "TERM": "dumb",
            "LANG": "C.UTF-8",
            "XDG_CONFIG_HOME": str(self._root / "xdg-config"),
            "XDG_DATA_HOME": str(self._root / "xdg-data"),
            "XDG_CACHE_HOME": str(self._root / "xdg-cache"),
            "PIPX_HOME": str(self._root / "pipx-home"),
            "PIPX_BIN_DIR": str(self._root / "pipx-bin"),
            "PYENV_ROOT": str(self._root / "pyenv"),
            "SLO_OS_RELEASE_FILE": str(self._root / "os-release"),
        }
        proxy_vars: dict[str, str] = {
            key: value for key, value in os.environ.items() if key.lower().endswith("_proxy")
        }
        return base | proxy_vars

    @property
    def calls(self) -> list[str]:
        """Return the logged invocations, one ``<name> <args>`` line each.

        Returns:
            list[str]: Recorded fake-tool invocations.
        """
        return [line for line in self._log.read_text().splitlines() if line.strip()]


@pytest.fixture
def fake_bin(tmp_path: Path) -> FakeBin:
    """Provide a fresh FakeBin rooted in a per-test temp dir.

    Args:
        tmp_path (Path): pytest temp dir.

    Returns:
        FakeBin: The stubbed PATH harness.
    """
    return FakeBin(root=tmp_path)


class TestOsDetection:
    """`slo_os_kind` normalizes `uname -s` to a stable token."""

    def test_macos(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        result = fake_bin.run(snippet="slo_os_kind")
        assert result.stdout.strip() == "macos"

    def test_linux(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        result = fake_bin.run(snippet="slo_os_kind")
        assert result.stdout.strip() == "linux"

    def test_unsupported(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="FreeBSD")
        result = fake_bin.run(snippet="slo_os_kind")
        assert result.stdout.strip() == "unsupported"


class TestLinuxDistro:
    """`slo_linux_distro` normalizes Debian-family Linux with builtins only."""

    def test_ubuntu(self, fake_bin: FakeBin) -> None:
        fake_bin.add_os_release(distro="ubuntu")
        result = fake_bin.run(snippet="slo_linux_distro")
        assert result.stdout.strip() == "debian"

    def test_debian(self, fake_bin: FakeBin) -> None:
        fake_bin.add_os_release(distro="debian")
        result = fake_bin.run(snippet="slo_linux_distro")
        assert result.stdout.strip() == "debian"

    def test_derivative_via_id_like(self, fake_bin: FakeBin) -> None:
        fake_bin.add_os_release(distro="pop", id_like="ubuntu debian")
        result = fake_bin.run(snippet="slo_linux_distro")
        assert result.stdout.strip() == "debian"

    def test_fedora_unsupported(self, fake_bin: FakeBin) -> None:
        fake_bin.add_os_release(distro="fedora")
        result = fake_bin.run(snippet="slo_linux_distro")
        assert result.stdout.strip() == "unsupported"

    def test_missing_file_unsupported(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(snippet="slo_linux_distro", env={"SLO_OS_RELEASE_FILE": "/missing/os-release"})
        assert result.stdout.strip() == "unsupported"


class TestSudo:
    """`slo_sudo` prefixes apt commands only when escalation is required."""

    def test_root_no_sudo(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(snippet="slo_sudo", env={"EUID": "0"})
        assert result.stdout.strip() == ""

    def test_nonroot_with_sudo(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="sudo")
        result = fake_bin.run(snippet="slo_sudo", env={"EUID": "1000"})
        assert result.stdout.strip() == "sudo"

    def test_nonroot_without_sudo(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(snippet="slo_sudo", env={"EUID": "1000"})
        assert result.stdout.strip() == ""


class TestEnsureBrew:
    """`slo_ensure_brew` is macOS-only."""

    def test_linux_is_noop(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        result = fake_bin.run(snippet="slo_ensure_brew")
        assert result.returncode == 0
        assert fake_bin.calls == []

    def test_macos_absent_installs(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        fake_bin.add(name="curl")
        result = fake_bin.run(snippet="slo_ensure_brew")
        assert result.returncode == 0
        assert any(call.startswith("curl -fsSL") for call in fake_bin.calls)


class TestEnsurePipx:
    """`slo_ensure_pipx` is a no-op when present, OS-aware when absent."""

    def test_present_skips_install(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_ensure_pipx")
        assert not any("install" in c for c in fake_bin.calls)

    def test_absent_macos_uses_brew(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        fake_bin.add(name="brew")
        fake_bin.run(snippet="slo_ensure_pipx")
        assert "brew install pipx" in fake_bin.calls

    def test_debian_prefers_apt_pipx(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add_os_release(distro="ubuntu")
        fake_bin.add(name="apt-get")
        fake_bin.run(snippet="slo_ensure_pipx")
        assert "apt-get install -y pipx" in fake_bin.calls

    def test_debian_falls_back_to_pip_when_apt_lacks_pipx(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add_os_release(distro="ubuntu")
        fake_bin.add(name="python3")
        apt_get: Path = fake_bin._bin / "apt-get"  # noqa: SLF001 - test harness setup.
        apt_get.write_text(
            "#!/bin/sh\n"
            'echo "apt-get $*" >> "$SLO_CALL_LOG"\n'
            'if [ "$1" = "install" ] && [ "$2" = "-y" ] && [ "$3" = "pipx" ]; then\n'
            "  exit 1\n"
            "fi\n"
            "exit 0\n"
        )
        apt_get.chmod(0o755)
        fake_bin.run(snippet="slo_ensure_pipx")
        assert "apt-get install -y pipx" in fake_bin.calls
        assert "apt-get install -y python3-pip python3-venv" in fake_bin.calls
        assert "python3 -m pip install --user pipx" in fake_bin.calls

    def test_non_debian_linux_uses_pip(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add_os_release(distro="fedora")
        fake_bin.add(name="python3")
        fake_bin.run(snippet="slo_ensure_pipx")
        assert "python3 -m pip install --user pipx" in fake_bin.calls


class TestEnsurePyenv:
    """`slo_ensure_pyenv` installs natively for the current OS when absent."""

    def test_present_skips_brew_install(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        fake_bin.add(name="pyenv")
        fake_bin.run(snippet="slo_ensure_pyenv")
        assert not any("brew install pyenv" in c for c in fake_bin.calls)

    def test_absent_installs_via_brew(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        fake_bin.add(name="brew")
        fake_bin.run(snippet="slo_ensure_pyenv")
        assert "brew install pyenv" in fake_bin.calls

    def test_linux_clones_pyenv(self, fake_bin: FakeBin, tmp_path: Path) -> None:
        root: Path = tmp_path / "pyenv-root"
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add(name="git")
        fake_bin.run(snippet="slo_ensure_pyenv", env={"PYENV_ROOT": str(root)})
        assert any(
            call == f"git clone --depth 1 https://github.com/pyenv/pyenv.git {root}"
            for call in fake_bin.calls
        )
        assert not any("brew install pyenv" in c for c in fake_bin.calls)

    def test_linux_skips_clone_when_root_exists(self, fake_bin: FakeBin, tmp_path: Path) -> None:
        root: Path = tmp_path / "pyenv-root"
        root.mkdir(parents=True)
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add(name="git")
        fake_bin.run(snippet="slo_ensure_pyenv", env={"PYENV_ROOT": str(root)})
        assert not any("git clone" in c for c in fake_bin.calls)


class TestEnsurePython:
    """`slo_ensure_python` installs the pinned version via pyenv (idempotent -s)."""

    def test_installs_pinned_default(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pyenv")
        fake_bin.run(snippet="slo_ensure_python")
        assert "pyenv install -s 3.11.7" in fake_bin.calls

    def test_respects_version_override(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pyenv")
        fake_bin.run(snippet="slo_ensure_python", env={"SLO_PYTHON_VERSION": "3.11.9"})
        assert "pyenv install -s 3.11.9" in fake_bin.calls


class TestEnsureBuildDeps:
    """`slo_ensure_build_deps` installs Linux pyenv headers only when needed."""

    def test_debian_installs_headers(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add_os_release(distro="debian")
        fake_bin.add(name="apt-get")
        result = fake_bin.run(snippet="slo_ensure_build_deps")
        assert result.returncode == 0
        assert any("libssl-dev" in c and "zlib1g-dev" in c for c in fake_bin.calls)

    def test_macos_noop(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        result = fake_bin.run(snippet="slo_ensure_build_deps")
        assert result.returncode == 0
        assert not any("apt-get" in c for c in fake_bin.calls)

    def test_non_debian_linux_noop(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add_os_release(distro="arch")
        result = fake_bin.run(snippet="slo_ensure_build_deps")
        assert result.returncode == 0
        assert not any("apt-get" in c for c in fake_bin.calls)


class TestEnsureHome:
    """`slo_ensure_home` honours an existing SLO_HOME, else defaults to ~/.slo."""

    def test_defaults_when_unset(self, fake_bin: FakeBin, tmp_path: Path) -> None:
        result = fake_bin.run(snippet="slo_ensure_home")
        printed = result.stdout.strip()
        assert printed.endswith("/.slo")
        assert Path(printed).is_dir()

    def test_honours_existing(self, fake_bin: FakeBin, tmp_path: Path) -> None:
        target = tmp_path / "custom-slo-home"
        result = fake_bin.run(snippet="slo_ensure_home", env={"SLO_HOME": str(target)})
        assert result.stdout.strip() == str(target)
        assert target.is_dir()


class TestEnsureGit:
    """`slo_ensure_git` is a no-op when present; OS-specific when absent."""

    def test_present_noop(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        fake_bin.add(name="git")
        result = fake_bin.run(snippet="slo_ensure_git")
        assert result.returncode == 0
        assert not any("install git" in c for c in fake_bin.calls)

    def test_absent_macos_uses_brew(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Darwin")
        fake_bin.add(name="brew")
        result = fake_bin.run(snippet="slo_ensure_git")
        assert result.returncode == 0
        assert "brew install git" in fake_bin.calls

    def test_absent_debian_uses_apt(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add_os_release(distro="ubuntu")
        fake_bin.add(name="apt-get")
        result = fake_bin.run(snippet="slo_ensure_git")
        assert result.returncode == 0
        assert "apt-get install -y git" in fake_bin.calls

    def test_absent_unsupported_distro_errors(self, fake_bin: FakeBin) -> None:
        fake_bin.add_uname(kernel="Linux")
        fake_bin.add_os_release(distro="fedora")
        result = fake_bin.run(snippet="slo_ensure_git")
        assert result.returncode == 1
        assert "git" in result.stderr.lower()


class TestAptRefresh:
    """`slo_apt_refresh` runs `apt-get update` at most once per invocation."""

    def test_refreshes_once(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="apt-get")
        result = fake_bin.run(snippet="slo_apt_install alpha; slo_apt_install beta")
        assert result.returncode == 0
        assert fake_bin.calls.count("apt-get update") == 1
        assert "apt-get install -y alpha" in fake_bin.calls
        assert "apt-get install -y beta" in fake_bin.calls


class TestInstall:
    """`slo_install` installs slo via pipx straight from the repo (no clone)."""

    def test_pipx_install_from_repo(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install")
        assert any(
            c.startswith("pipx install --force --python ")
            and "git+https://gitlab.com/core-27/slo.git@main" in c
            for c in fake_bin.calls
        )

    def test_resolves_concrete_interpreter_when_pyenv_present(
        self, fake_bin: FakeBin, tmp_path: Path
    ) -> None:
        # When pyenv yields a real pinned interpreter, pipx is pointed at the
        # absolute path, not the version-dependent `python3.11` shim.
        root = tmp_path / "pyenv"
        interp = root / "versions" / "3.11.7" / "bin" / "python3.11"
        interp.parent.mkdir(parents=True)
        interp.write_text("#!/bin/sh\n")
        interp.chmod(0o755)
        fake_bin.add(name="pipx")
        (fake_bin._bin / "pyenv").write_text(  # noqa: SLF001 — test harness.
            f'#!/bin/sh\necho "pyenv $*" >> "$SLO_CALL_LOG"\n[ "$1" = "root" ] && echo "{root}"\nexit 0\n'
        )
        (fake_bin._bin / "pyenv").chmod(0o755)  # noqa: SLF001 — test harness.
        fake_bin.run(snippet="slo_install")
        assert any(f"--python {interp} " in c for c in fake_bin.calls)

    def test_never_clones(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pipx")
        fake_bin.add(name="git")
        fake_bin.run(snippet="slo_install")
        assert not any("clone" in c for c in fake_bin.calls)

    def test_respects_ref_override(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install", env={"SLO_REF": "v1.2.3"})
        assert any("git+https://gitlab.com/core-27/slo.git@v1.2.3" in c for c in fake_bin.calls)

    def test_ignores_legacy_repository_credentials(self, fake_bin: FakeBin) -> None:
        # The public installer must not put deploy tokens or PATs into the VCS
        # URL, even if they remain in a user's environment from an old install.
        fake_bin.add(name="pipx")
        fake_bin.run(
            snippet="slo_install",
            env={
                "SLO_DEPLOY_TOKEN_USERNAME": "gitlab+deploy-token-7",
                "SLO_DEPLOY_TOKEN": "dt-secret",
                "SLO_INSTALL_TOKEN": "glpat-secret",
                "SLO_USERNAME": "legacy-user",
                "SLO_TOKEN": "legacy-token",
            },
        )
        assert any("git+https://gitlab.com/core-27/slo.git@main" in c for c in fake_bin.calls)
        assert not any("@gitlab.com" in c for c in fake_bin.calls)
        assert not any("dt-secret" in c or "glpat-secret" in c or "legacy-token" in c for c in fake_bin.calls)

    def test_targets_slo_subdirectory(self, fake_bin: FakeBin) -> None:
        # The project lives in the repo's slo/ subdir, so pip must be told where
        # pyproject.toml is via the #subdirectory fragment.
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install")
        assert any(
            "git+https://gitlab.com/core-27/slo.git@main#subdirectory=slo" in c for c in fake_bin.calls
        )

    def test_subdir_override_empty_installs_from_root(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install", env={"SLO_REPO_SUBDIR": ""})
        assert not any("#subdirectory=" in c for c in fake_bin.calls)


class TestRepoConfig:
    """SLO_REPO_URL / SLO_REF are defined by the script and env-overridable."""

    def test_default_repo_url(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(snippet='echo "$SLO_REPO_URL"')
        assert result.stdout.strip() == "https://gitlab.com/core-27/slo.git"

    def test_default_ref_is_main(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(snippet='echo "$SLO_REF"')
        assert result.stdout.strip() == "main"

    def test_repo_url_env_override(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(
            snippet='echo "$SLO_REPO_URL"',
            env={"SLO_REPO_URL": "git@gitlab.com:core-27/slo.git"},
        )
        assert result.stdout.strip() == "git@gitlab.com:core-27/slo.git"


class TestResolveVendoredSkillsDir:
    """`slo_resolve_vendored_skills_dir` resolves ONLY via pipx Location metadata."""

    def test_resolve_vendored_skills_dir_when_pipx_location_has_index(self, fake_bin: FakeBin) -> None:
        """Happy path: physical absolute `<Location>/skills`, clean stdout."""
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        result = fake_bin.run(snippet="slo_resolve_vendored_skills_dir")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(location / "skills")
        assert "Location" not in result.stdout

    def test_resolve_vendored_skills_dir_when_location_is_missing(self, fake_bin: FakeBin) -> None:
        """No `Location:` field → non-zero, stderr diagnostic, empty stdout."""
        fake_bin.write_fake_pipx(location=None)
        result = fake_bin.run(snippet="slo_resolve_vendored_skills_dir")
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert result.stdout.strip() == ""

    def test_resolve_vendored_skills_dir_when_location_is_ambiguous(self, fake_bin: FakeBin) -> None:
        """Two `Location:` lines → non-zero (refuse to guess)."""
        location_a: Path = fake_bin.make_package_location(name="loc-a")
        location_b: Path = fake_bin.make_package_location(name="loc-b")
        pipx_path: Path = fake_bin._bin / "pipx"  # noqa: SLF001 — test harness setup.
        pipx_path.write_text(
            "#!/bin/sh\n"
            'echo "pipx $*" >> "$SLO_CALL_LOG"\n'
            'if [ "$1" = "runpip" ]; then\n'
            '  echo "Name: slo"\n'
            f'  echo "Location: {location_a}"\n'
            f'  echo "Location: {location_b}"\n'
            "  exit 0\n"
            "fi\n"
        )
        pipx_path.chmod(0o755)
        result = fake_bin.run(snippet="slo_resolve_vendored_skills_dir")
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert result.stdout.strip() == ""

    def test_resolve_vendored_skills_dir_when_runpip_fails(self, fake_bin: FakeBin) -> None:
        """`pipx runpip slo show slo` failing → non-zero, no stdout path."""
        pipx_path: Path = fake_bin._bin / "pipx"  # noqa: SLF001 — test harness setup.
        pipx_path.write_text("#!/bin/sh\n" 'echo "pipx $*" >> "$SLO_CALL_LOG"\nexit 1\n')
        pipx_path.chmod(0o755)
        result = fake_bin.run(snippet="slo_resolve_vendored_skills_dir")
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert result.stdout.strip() == ""

    def test_resolve_vendored_skills_dir_when_index_is_missing(self, fake_bin: FakeBin) -> None:
        """`<Location>/skills` without a readable INDEX.md is rejected."""
        location: Path = fake_bin.make_package_location(index=False)
        fake_bin.write_fake_pipx(location=location)
        result = fake_bin.run(snippet="slo_resolve_vendored_skills_dir")
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert "INDEX.md" in result.stderr
        assert result.stdout.strip() == ""

    def test_resolve_vendored_skills_dir_when_candidate_is_not_a_directory(self, fake_bin: FakeBin) -> None:
        """`<Location>/skills` as a regular file is rejected."""
        location: Path = fake_bin._root / "broken-location"  # noqa: SLF001 — test harness setup.
        location.mkdir(parents=True)
        (location / "skills").write_text("not a directory\n")
        fake_bin.write_fake_pipx(location=location)
        result = fake_bin.run(snippet="slo_resolve_vendored_skills_dir")
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert result.stdout.strip() == ""

    def test_resolve_vendored_skills_dir_never_guesses_pipx_layout(self, fake_bin: FakeBin) -> None:
        """A populated default pipx root is NOT a fallback: metadata failure is terminal."""
        default_root: Path = (
            fake_bin._root / "pipx-home" / "venvs" / "slo" / "lib" / "python3.11" / "site-packages"
        )  # noqa: SLF001
        (default_root / "skills").mkdir(parents=True)
        (default_root / "skills" / "INDEX.md").write_text("# index\n")
        fake_bin.write_fake_pipx(location=None)
        result = fake_bin.run(snippet="slo_resolve_vendored_skills_dir")
        assert result.returncode != 0
        assert str(default_root) not in result.stdout


class TestWriteManagedEnvironmentFile:
    """`slo_write_managed_environment_file` owns exactly one marked 0644 file."""

    def _write(self, fake_bin: FakeBin, *, skills_dir: Path) -> subprocess.CompletedProcess[str]:
        """Invoke the writer with an explicit vendored skills directory.

        Args:
            fake_bin (FakeBin): The isolated harness.
            skills_dir (Path): Resolved vendored skills directory to persist.

        Returns:
            subprocess.CompletedProcess[str]: The writer's completed process.
        """
        return fake_bin.run(
            snippet=f'slo_write_managed_environment_file "{skills_dir}"',
        )

    def test_write_managed_environment_creates_marked_0644_file(self, fake_bin: FakeBin) -> None:
        """Fresh write: marker pair, POSIX-quoted skills path, mode 0644."""
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = self._write(fake_bin, skills_dir=skills_dir)
        assert result.returncode == 0, result.stderr
        managed: Path = fake_bin.managed_env_file
        assert managed.is_file()
        mode: int = managed.stat().st_mode & 0o777
        assert mode == 0o644, oct(mode)
        text: str = managed.read_text()
        assert marker_pair_count(text=text) == 1
        assert '[ -z "${SLO_HOME+x}" ]' in text
        assert '[ -z "${SLO_SKILLS_DIR+x}" ]' in text
        assert "SLO_SKILLS_DIR='" in text
        assert str(skills_dir) not in text or f"'{skills_dir}'" in text
        assert "$HOME" not in text.split("SLO_SKILLS_DIR=")[1].splitlines()[0]

    def test_environment_file_when_home_contains_spaces_and_apostrophe(self, fake_bin: FakeBin) -> None:
        """Sourcing exports the LITERAL paths — no splitting, no code execution."""
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = self._write(fake_bin, skills_dir=skills_dir)
        assert result.returncode == 0, result.stderr
        sourced = fake_bin.run(
            snippet='. "$HOME/.slo/shell/environment.sh" && printf "%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR"',
        )
        assert sourced.returncode == 0, sourced.stderr
        lines: list[str] = sourced.stdout.splitlines()
        assert lines == [f"{fake_bin.home}/.slo", str(skills_dir)]

    def test_write_managed_environment_replaces_marked_file_atomically(self, fake_bin: FakeBin) -> None:
        """A previously written marked file is refreshed with the new path."""
        old_skills: Path = fake_bin.make_package_location(name="old") / "skills"
        new_skills: Path = fake_bin.make_package_location(name="new") / "skills"
        first = self._write(fake_bin, skills_dir=old_skills)
        assert first.returncode == 0, first.stderr
        second = self._write(fake_bin, skills_dir=new_skills)
        assert second.returncode == 0, second.stderr
        text: str = fake_bin.managed_env_file.read_text()
        assert marker_pair_count(text=text) == 1
        assert str(new_skills) in text
        assert str(old_skills) not in text

    def test_write_managed_environment_when_content_is_already_current(self, fake_bin: FakeBin) -> None:
        """Identical bytes → `already current`, and the file is not replaced."""
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        first = self._write(fake_bin, skills_dir=skills_dir)
        assert first.returncode == 0, first.stderr
        before: bytes = fake_bin.managed_env_file.read_bytes()
        inode_before: int = fake_bin.managed_env_file.stat().st_ino
        second = self._write(fake_bin, skills_dir=skills_dir)
        assert second.returncode == 0, second.stderr
        assert "already current" in second.stderr
        assert fake_bin.managed_env_file.read_bytes() == before
        assert fake_bin.managed_env_file.stat().st_ino == inode_before

    def test_write_managed_environment_when_existing_file_is_unmarked(self, fake_bin: FakeBin) -> None:
        """An unmarked user file at the managed path is refused, byte-identical."""
        managed: Path = fake_bin.managed_env_file
        managed.parent.mkdir(parents=True, exist_ok=True)
        managed.write_text("# my own file\nexport SLO_HOME=/custom\n")
        before: bytes = managed.read_bytes()
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = self._write(fake_bin, skills_dir=skills_dir)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert managed.read_bytes() == before

    def test_write_managed_environment_when_markers_are_malformed(self, fake_bin: FakeBin) -> None:
        """A file with an unmatched marker is refused without mutation."""
        managed: Path = fake_bin.managed_env_file
        managed.parent.mkdir(parents=True, exist_ok=True)
        managed.write_text(f"{MANAGED_ENV_MARK_BEGIN}\nexport SLO_HOME=x\n")
        before: bytes = managed.read_bytes()
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = self._write(fake_bin, skills_dir=skills_dir)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert managed.read_bytes() == before

    def test_write_managed_environment_when_target_is_symlink(self, fake_bin: FakeBin) -> None:
        """A symlink at the managed path is refused; its target is untouched."""
        managed: Path = fake_bin.managed_env_file
        managed.parent.mkdir(parents=True, exist_ok=True)
        external_root: Path = fake_bin._root / "external-symlink-target"  # noqa: SLF001 - fixture boundary.
        external_root.mkdir()
        outside: Path = external_root / "elsewhere.sh"
        outside.write_text("# untouched\n")
        managed.symlink_to(outside)
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = self._write(fake_bin, skills_dir=skills_dir)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert managed.is_symlink()
        assert outside.read_text() == "# untouched\n"

    def test_write_managed_environment_when_target_is_a_directory(self, fake_bin: FakeBin) -> None:
        """A directory at the managed path is refused and left in place."""
        managed: Path = fake_bin.managed_env_file
        managed.mkdir(parents=True)
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = self._write(fake_bin, skills_dir=skills_dir)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert managed.is_dir()

    def test_write_managed_environment_when_target_is_a_fifo(self, fake_bin: FakeBin) -> None:
        """A non-regular file (FIFO) at the managed path is refused, untouched."""
        managed: Path = fake_bin.managed_env_file
        managed.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(managed)
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = self._write(fake_bin, skills_dir=skills_dir)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert stat.S_ISFIFO(managed.stat().st_mode)

    def test_write_managed_environment_when_skills_dir_is_missing(self, fake_bin: FakeBin) -> None:
        """A non-existent skills dir is refused before any file is created."""
        result = self._write(fake_bin, skills_dir=fake_bin.home / "nope" / "skills")
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert not fake_bin.managed_env_file.exists()


class TestReconcileShellSourceBlock:
    """`slo_reconcile_shell_source_block` edits exactly one bounded block per profile."""

    def _reconcile(self, fake_bin: FakeBin, *, profile: Path) -> subprocess.CompletedProcess[str]:
        """Invoke the one-profile reconciler against an explicit path.

        Args:
            fake_bin (FakeBin): The isolated harness.
            profile (Path): Profile file path to reconcile.

        Returns:
            subprocess.CompletedProcess[str]: The reconciler's completed process.
        """
        return fake_bin.run(snippet=f'slo_reconcile_shell_source_block "{profile}"')

    def test_reconcile_shell_source_block_when_profile_is_missing(self, fake_bin: FakeBin) -> None:
        """A missing profile is created with exactly one source block."""
        profile: Path = fake_bin.profile_paths[".bashrc"]
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode == 0, result.stderr
        text: str = profile.read_text()
        assert marker_pair_count(text=text) == 1
        assert '[ -r "$HOME/.slo/shell/environment.sh" ]' in text
        assert '. "$HOME/.slo/shell/environment.sh"' in text

    def test_reconcile_shell_source_block_when_no_markers(self, fake_bin: FakeBin) -> None:
        """An existing markerless profile gains one appended block, content kept."""
        profile: Path = fake_bin.profile_paths[".bashrc"]
        profile.write_text("export EDITOR=vim\nalias ll='ls -la'\n")
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode == 0, result.stderr
        text: str = profile.read_text()
        assert text.startswith("export EDITOR=vim\nalias ll='ls -la'\n")
        assert marker_pair_count(text=text) == 1

    def test_reconcile_shell_source_block_when_rerun(self, fake_bin: FakeBin) -> None:
        """Rerun: exactly one marker pair, already-current, outside content intact."""
        profile: Path = fake_bin.profile_paths[".bashrc"]
        profile.write_text("# user header\n")
        first = self._reconcile(fake_bin, profile=profile)
        assert first.returncode == 0, first.stderr
        second = self._reconcile(fake_bin, profile=profile)
        assert second.returncode == 0, second.stderr
        assert "already current" in second.stderr
        text: str = profile.read_text()
        assert text.startswith("# user header\n")
        assert text.count(MANAGED_ENV_MARK_BEGIN) == 1
        assert text.count(MANAGED_ENV_MARK_END) == 1

    def test_reconcile_shell_source_block_replaces_existing_pair(self, fake_bin: FakeBin) -> None:
        """One complete stale pair is replaced in place; surrounding bytes kept."""
        profile: Path = fake_bin.profile_paths[".zshenv"]
        profile.write_text(
            "# before\n"
            f"{MANAGED_ENV_MARK_BEGIN}\n"
            ". /old/stale/path.sh\n"
            f"{MANAGED_ENV_MARK_END}\n"
            "# after\n"
        )
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode == 0, result.stderr
        text: str = profile.read_text()
        assert text.startswith("# before\n")
        assert text.endswith("# after\n")
        assert "/old/stale/path.sh" not in text
        assert marker_pair_count(text=text) == 1
        assert '. "$HOME/.slo/shell/environment.sh"' in text

    def test_reconcile_shell_source_block_when_markers_are_malformed(self, fake_bin: FakeBin) -> None:
        """An unmatched begin marker refuses without touching the file."""
        profile: Path = fake_bin.profile_paths[".profile"]
        profile.write_text(f"# mine\n{MANAGED_ENV_MARK_BEGIN}\n# unfinished\n")
        before: bytes = profile.read_bytes()
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert profile.read_bytes() == before

    def test_reconcile_shell_source_block_when_multiple_pairs(self, fake_bin: FakeBin) -> None:
        """Two complete pairs refuse without touching the file."""
        profile: Path = fake_bin.profile_paths[".profile"]
        pair: str = (
            f"{MANAGED_ENV_MARK_BEGIN}\n" '. "$HOME/.slo/shell/environment.sh"\n' f"{MANAGED_ENV_MARK_END}\n"
        )
        profile.write_text(f"# mine\n{pair}{pair}")
        before: bytes = profile.read_bytes()
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert profile.read_bytes() == before

    def test_reconcile_shell_source_block_preserves_every_byte_outside_the_replaced_block(
        self, fake_bin: FakeBin
    ) -> None:
        """Replacement must be byte-exact: prefix and suffix (including a trailing
        blank-line run) survive unchanged; no command-substitution newline loss."""
        profile: Path = fake_bin.profile_paths[".bash_profile"]
        prefix: bytes = b"# user preamble\nexport EDITOR=vim\n"
        stale_pair: bytes = (
            MANAGED_ENV_MARK_BEGIN.encode() + b"\n"
            b"# old managed line\n" + MANAGED_ENV_MARK_END.encode() + b"\n"
        )
        suffix: bytes = b"# trailing user content\n\n\n\n"
        profile.write_bytes(prefix + stale_pair + suffix)
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode == 0, result.stderr
        assert profile.read_bytes() == prefix + CANONICAL_SOURCE_BLOCK + suffix

    def test_reconcile_shell_source_block_when_suffix_is_only_trailing_newlines(
        self, fake_bin: FakeBin
    ) -> None:
        """A block followed by nothing but blank lines keeps every newline byte."""
        profile: Path = fake_bin.profile_paths[".bashrc"]
        stale_pair: bytes = (
            MANAGED_ENV_MARK_BEGIN.encode() + b"\n"
            b"# old managed line\n" + MANAGED_ENV_MARK_END.encode() + b"\n"
        )
        profile.write_bytes(stale_pair + b"\n\n\n")
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode == 0, result.stderr
        assert profile.read_bytes() == CANONICAL_SOURCE_BLOCK + b"\n\n\n"

    def test_reconcile_shell_source_block_replacement_happens_via_atomic_rename(
        self, fake_bin: FakeBin
    ) -> None:
        """A replaced block lands via same-directory temp + rename, not in-place
        rewriting: the profile gets a fresh inode and no temp files leak."""
        profile: Path = fake_bin.profile_paths[".bashrc"]
        stale_pair: bytes = (
            MANAGED_ENV_MARK_BEGIN.encode() + b"\n"
            b"# old managed line\n" + MANAGED_ENV_MARK_END.encode() + b"\n"
        )
        profile.write_bytes(b"# before\n" + stale_pair)
        inode_before: int = profile.stat().st_ino
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode == 0, result.stderr
        assert profile.stat().st_ino != inode_before
        leftovers: list[Path] = [
            path for path in profile.parent.iterdir() if path.name.startswith(profile.name + ".slo.")
        ]
        assert leftovers == []

    def test_reconcile_shell_source_block_when_target_is_a_fifo(self, fake_bin: FakeBin) -> None:
        """A non-regular file (FIFO) at the profile path is refused, untouched."""
        profile: Path = fake_bin.profile_paths[".profile"]
        os.mkfifo(profile)
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert stat.S_ISFIFO(profile.stat().st_mode)

    def test_reconcile_shell_source_block_when_target_is_symlink(self, fake_bin: FakeBin) -> None:
        """A symlink profile path refuses; the link target is untouched."""
        profile: Path = fake_bin.profile_paths[".bashrc"]
        external_root: Path = fake_bin._root / "external-symlink-target"  # noqa: SLF001 - fixture boundary.
        external_root.mkdir()
        outside: Path = external_root / "real-bashrc"
        outside.write_text("# real\n")
        profile.symlink_to(outside)
        result = self._reconcile(fake_bin, profile=profile)
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert profile.is_symlink()
        assert outside.read_text() == "# real\n"


class TestInstallShellEnvironment:
    """`slo_install_shell_environment` applies the fixed Bash/Zsh/POSIX matrix."""

    def test_install_shell_environment_writes_all_four_profiles(self, fake_bin: FakeBin) -> None:
        """Every supported profile gains exactly one canonical source block."""
        result = fake_bin.run(snippet="slo_install_shell_environment")
        assert result.returncode == 0, result.stderr
        for name, path in fake_bin.profile_paths.items():
            text: str = path.read_text()
            assert marker_pair_count(text=text) == 1, name
            assert '. "$HOME/.slo/shell/environment.sh"' in text, name

    def test_install_shell_environment_preserves_existing_content(self, fake_bin: FakeBin) -> None:
        """Pre-existing user content survives in every profile."""
        for name, path in fake_bin.profile_paths.items():
            path.write_text(f"# {name} user content\n")
        result = fake_bin.run(snippet="slo_install_shell_environment")
        assert result.returncode == 0, result.stderr
        for name, path in fake_bin.profile_paths.items():
            assert path.read_text().startswith(f"# {name} user content\n")

    def test_install_shell_environment_refuses_malformed_profile(self, fake_bin: FakeBin) -> None:
        """One malformed profile fails the matrix; the file stays untouched."""
        bad: Path = fake_bin.profile_paths[".zshenv"]
        bad.write_text(f"{MANAGED_ENV_MARK_BEGIN}\n# broken\n")
        before: bytes = bad.read_bytes()
        result = fake_bin.run(snippet="slo_install_shell_environment")
        assert result.returncode != 0
        assert "error:" in result.stderr
        assert bad.read_bytes() == before


class TestFinalizeShellEnvironment:
    """`slo_finalize_shell_environment` gateway: resolve → write → reconcile."""

    def test_finalize_shell_environment_happy_path(self, fake_bin: FakeBin) -> None:
        """Full finalisation: managed file plus one block per profile."""
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        result = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert result.returncode == 0, result.stderr
        assert fake_bin.managed_env_file.is_file()
        text: str = fake_bin.managed_env_file.read_text()
        assert str(location / "skills") in text
        for name, path in fake_bin.profile_paths.items():
            assert marker_pair_count(text=path.read_text()) == 1, name

    def test_finalize_shell_environment_when_metadata_is_missing(self, fake_bin: FakeBin) -> None:
        """No pipx Location → non-zero, no managed file, no profile blocks."""
        fake_bin.write_fake_pipx(location=None)
        result = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert result.returncode != 0
        assert not fake_bin.managed_env_file.exists()
        for path in fake_bin.profile_paths.values():
            assert not path.exists()

    def test_finalize_shell_environment_when_pipx_install_fails(self, fake_bin: FakeBin) -> None:
        """A failed `pipx install` must produce NO persistent shell state."""
        pipx_path: Path = fake_bin._bin / "pipx"  # noqa: SLF001 — test harness setup.
        pipx_path.write_text(
            "#!/bin/sh\n"
            'echo "pipx $*" >> "$SLO_CALL_LOG"\n'
            'if [ "$1" = "install" ]; then\n'
            "  exit 1\n"
            "fi\n"
            "exit 1\n"
        )
        pipx_path.chmod(0o755)
        result = fake_bin.run(snippet="slo_install || exit 99; slo_finalize_shell_environment")
        assert result.returncode == 99
        assert not fake_bin.managed_env_file.exists()
        for path in fake_bin.profile_paths.values():
            assert not path.exists()

    def test_finalize_shell_environment_rerun_is_idempotent(self, fake_bin: FakeBin) -> None:
        """A second run keeps one block per profile and a current managed file."""
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        first = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert first.returncode == 0, first.stderr
        second = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert second.returncode == 0, second.stderr
        assert "already current" in second.stderr
        for name, path in fake_bin.profile_paths.items():
            text: str = path.read_text()
            assert text.count(MANAGED_ENV_MARK_BEGIN) == 1, name

    def test_finalize_shell_environment_rerun_refreshes_moved_location(self, fake_bin: FakeBin) -> None:
        """A pipx Location change is picked up on rerun of the installer."""
        old_location: Path = fake_bin.make_package_location(name="old")
        fake_bin.write_fake_pipx(location=old_location)
        first = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert first.returncode == 0, first.stderr
        assert str(old_location / "skills") in fake_bin.managed_env_file.read_text()
        new_location: Path = fake_bin.make_package_location(name="new")
        fake_bin.write_fake_pipx(location=new_location)
        second = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert second.returncode == 0, second.stderr
        text: str = fake_bin.managed_env_file.read_text()
        assert str(new_location / "skills") in text
        assert str(old_location / "skills") not in text
        for name, path in fake_bin.profile_paths.items():
            assert path.read_text().count(MANAGED_ENV_MARK_BEGIN) == 1, name

    def test_finalize_preserves_user_skills_and_absent_user_workflows(self, fake_bin: FakeBin) -> None:
        """User skills are untouched; user workflows stay absent; no legacy copy."""
        user_skill: Path = fake_bin.home / ".slo" / "user_skills" / "my-skill" / "SKILL.md"
        user_skill.parent.mkdir(parents=True)
        user_skill.write_text("---\nname: my-skill\n---\n")
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        result = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert result.returncode == 0, result.stderr
        assert user_skill.read_text() == "---\nname: my-skill\n---\n"
        assert not (fake_bin.home / ".slo" / "user_workflows").exists()
        assert not (fake_bin.home / ".slo" / "skills").exists()


class TestFreshShellStartup:
    """Real shells started against the isolated HOME inherit the defaults."""

    def _finalize(self, fake_bin: FakeBin) -> Path:
        """Run finalisation against a fake package location.

        Args:
            fake_bin (FakeBin): The isolated harness.

        Returns:
            Path: The fake package location used.
        """
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        result = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert result.returncode == 0, result.stderr
        return location

    def test_bash_login_shell_exports_defaults(self, fake_bin: FakeBin) -> None:
        """`bash --login` reads `.bash_profile` and exports both defaults."""
        location: Path = self._finalize(fake_bin)
        result = fake_bin.run_shell_env(
            args=[BASH, "--login", "-c", 'printf "%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR"'],
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [f"{fake_bin.home}/.slo", str(location / "skills")]

    def test_bash_interactive_non_login_shell_exports_defaults(self, fake_bin: FakeBin) -> None:
        """`bash -i` reads `.bashrc` and exports both defaults."""
        location: Path = self._finalize(fake_bin)
        result = fake_bin.run_shell_env(
            args=[BASH, "-i", "-c", 'printf "%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR"'],
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [f"{fake_bin.home}/.slo", str(location / "skills")]

    @pytest.mark.skipif(ZSH is None, reason="zsh not installed on the test host")
    def test_zsh_login_and_interactive_non_login_shell_export_defaults(self, fake_bin: FakeBin) -> None:
        """Both zsh modes read `.zshenv` and export both defaults."""
        assert ZSH is not None
        location: Path = self._finalize(fake_bin)
        for args in (
            [ZSH, "--login", "-c", 'printf "%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR"'],
            [ZSH, "-i", "-c", 'printf "%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR"'],
        ):
            result = fake_bin.run_shell_env(args=args)
            assert result.returncode == 0, result.stderr
            assert result.stdout.splitlines() == [f"{fake_bin.home}/.slo", str(location / "skills")]

    def test_posix_sh_login_shell_exports_defaults(self, fake_bin: FakeBin) -> None:
        """A genuine POSIX login shell (``dash -l`` / ``sh -l``) reads ``.profile``
        and exports both defaults — not a manual source from a Bash subshell."""
        login_shell: str | None = DASH or SH
        if login_shell is None:
            pytest.skip("no POSIX sh (dash or sh) available on the test host")
        location: Path = self._finalize(fake_bin)
        result = fake_bin.run_shell_env(
            args=[
                login_shell,
                "-l",
                "-c",
                'printf "%s\n%s\n" "${SLO_HOME:-}" "${SLO_SKILLS_DIR:-}"',
            ],
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [f"{fake_bin.home}/.slo", str(location / "skills")]

    def test_explicit_environment_override_survives_source(self, fake_bin: FakeBin) -> None:
        """Pre-exported SLO_HOME / SLO_SKILLS_DIR win over the managed defaults."""
        self._finalize(fake_bin)
        custom_home: Path = fake_bin.home / "custom-slo-home"
        custom_skills: Path = fake_bin.home / "custom-skills"
        result = fake_bin.run_shell_env(
            args=[BASH, "--login", "-c", 'printf "%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR"'],
            env={"SLO_HOME": str(custom_home), "SLO_SKILLS_DIR": str(custom_skills)},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [str(custom_home), str(custom_skills)]


class TestManagedEnvironmentKnowledgeBaseDefault:
    """The managed file also defaults ``SLO_KB_DIR`` — variable only, never a directory."""

    PRINT: str = 'printf "%s\n%s\n" "$SLO_HOME" "$SLO_KB_DIR"'

    def _source(self, fake_bin: FakeBin, *, env: dict[str, str] | None = None) -> list[str]:
        """Write the managed file, source it under ``env``, and return SLO_HOME / SLO_KB_DIR.

        Args:
            fake_bin (FakeBin): The isolated harness.
            env (dict[str, str] | None): Variables exported before sourcing.

        Returns:
            list[str]: ``[SLO_HOME, SLO_KB_DIR]`` as seen after sourcing.
        """
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        written = fake_bin.run(snippet=f'slo_write_managed_environment_file "{skills_dir}"')
        assert written.returncode == 0, written.stderr
        sourced = fake_bin.run(snippet=f'. "$HOME/.slo/shell/environment.sh" && {self.PRINT}', env=env)
        assert sourced.returncode == 0, sourced.stderr
        return sourced.stdout.splitlines()

    def test_managed_file_guards_slo_kb_dir_by_existence(self, fake_bin: FakeBin) -> None:
        skills_dir: Path = fake_bin.make_package_location() / "skills"
        result = fake_bin.run(snippet=f'slo_write_managed_environment_file "{skills_dir}"')
        assert result.returncode == 0, result.stderr
        text: str = fake_bin.managed_env_file.read_text()
        assert '[ -z "${SLO_KB_DIR+x}" ]' in text
        assert text.index("SLO_HOME=") < text.index("SLO_KB_DIR=")

    def test_defaults_under_home_dot_slo_when_nothing_is_set(self, fake_bin: FakeBin) -> None:
        home_dir: str = f"{fake_bin.home}/.slo"
        assert self._source(fake_bin) == [home_dir, f"{home_dir}/KnowledgeBase/KB"]

    def test_follows_a_preset_slo_home(self, fake_bin: FakeBin) -> None:
        custom: str = str(fake_bin.home / "custom slo home")
        assert self._source(fake_bin, env={"SLO_HOME": custom}) == [custom, f"{custom}/KnowledgeBase/KB"]

    def test_kb_dir_is_used_when_slo_kb_dir_is_unset(self, fake_bin: FakeBin) -> None:
        alias: str = str(fake_bin.home / "alias KB")
        assert self._source(fake_bin, env={"KB_DIR": alias})[1] == alias

    def test_preset_slo_kb_dir_wins_over_kb_dir(self, fake_bin: FakeBin) -> None:
        canonical: str = str(fake_bin.home / "canonical KB")
        env: dict[str, str] = {"SLO_KB_DIR": canonical, "KB_DIR": str(fake_bin.home / "alias")}
        assert self._source(fake_bin, env=env)[1] == canonical

    def test_a_set_but_empty_slo_kb_dir_is_left_alone(self, fake_bin: FakeBin) -> None:
        """Existence, not value, decides: the managed file never overrides a set variable."""
        assert self._source(fake_bin, env={"SLO_KB_DIR": ""})[1] == ""

    def test_kb_path_with_apostrophe_is_not_executed_or_split(self, fake_bin: FakeBin) -> None:
        tricky: str = str(fake_bin.home / "it's $(touch pwned) KB")
        assert self._source(fake_bin, env={"KB_DIR": tricky})[1] == tricky
        assert not (Path.cwd() / "pwned").exists()

    def test_sourcing_never_creates_the_kb_directory(self, fake_bin: FakeBin) -> None:
        self._source(fake_bin)
        assert not (fake_bin.home / ".slo" / "KnowledgeBase").exists()

    def test_fresh_login_shell_exports_the_kb_default(self, fake_bin: FakeBin) -> None:
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        finalized = fake_bin.run(snippet="slo_finalize_shell_environment")
        assert finalized.returncode == 0, finalized.stderr
        result = fake_bin.run_shell_env(args=[BASH, "--login", "-c", self.PRINT])
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines()[1] == f"{fake_bin.home}/.slo/KnowledgeBase/KB"


class TestMainDispatch:
    """Direct installer dispatch keeps both finalizers isolated and ordered."""

    def test_normal_install_orders_finalizers_then_path_and_cheatsheet(self, fake_bin: FakeBin) -> None:
        """The supported normal path cannot report success before launcher hardening completes."""
        result = fake_bin.run(snippet="""
            slo_ensure_brew() { :; }
            slo_ensure_git() { :; }
            slo_ensure_build_deps() { :; }
            slo_ensure_pyenv() { :; }
            slo_ensure_python() { :; }
            slo_ensure_pipx() { :; }
            slo_ensure_home() { :; }
            slo_install() { printf 'install\\n' >> "$SLO_CALL_LOG"; }
            slo_finalize_shell_environment() { printf 'shell\\n' >> "$SLO_CALL_LOG"; }
            slo_finalize_isolated_launcher() { printf 'launcher\\n' >> "$SLO_CALL_LOG"; }
            slo_ensure_local_bin_on_path() { printf 'path\\n' >> "$SLO_CALL_LOG"; }
            slo_print_path() { printf 'cheatsheet\\n' >> "$SLO_CALL_LOG"; }
            main
            """)

        assert result.returncode == 0, result.stderr
        assert fake_bin.calls == ["install", "shell", "launcher", "path", "cheatsheet"]

    def test_normal_install_stops_after_launcher_finalization_failure(self, fake_bin: FakeBin) -> None:
        """A failed launcher finalizer prevents PATH/profile follow-up and success messaging."""
        result = fake_bin.run(snippet="""
            slo_ensure_brew() { :; }
            slo_ensure_git() { :; }
            slo_ensure_build_deps() { :; }
            slo_ensure_pyenv() { :; }
            slo_ensure_python() { :; }
            slo_ensure_pipx() { :; }
            slo_ensure_home() { :; }
            slo_install() { printf 'install\\n' >> "$SLO_CALL_LOG"; }
            slo_finalize_shell_environment() { printf 'shell\\n' >> "$SLO_CALL_LOG"; }
            slo_finalize_isolated_launcher() { printf 'launcher\\n' >> "$SLO_CALL_LOG"; return 1; }
            slo_ensure_local_bin_on_path() { printf 'path\\n' >> "$SLO_CALL_LOG"; }
            slo_print_path() { printf 'cheatsheet\\n' >> "$SLO_CALL_LOG"; }
            main
            """)

        assert result.returncode != 0
        assert fake_bin.calls == ["install", "shell", "launcher"]

    def test_finalize_environment_does_not_call_launcher_finalizer(self, fake_bin: FakeBin) -> None:
        """The existing shell-only mode never gains a launcher side effect."""
        result = fake_bin.run(snippet="""
            slo_finalize_shell_environment() { printf 'shell\\n' >> "$SLO_CALL_LOG"; }
            slo_finalize_isolated_launcher() { printf 'launcher\\n' >> "$SLO_CALL_LOG"; }
            main --finalize-environment
            """)

        assert result.returncode == 0, result.stderr
        assert fake_bin.calls == ["shell"]


class TestFinalizeEnvironmentMode:
    """``install.sh --finalize-environment`` runs only the shell-environment step.

    ``slo update`` calls this mode on the just-installed copy, so it must never
    provision toolchains or reinstall the package.
    """

    def _run(self, fake_bin: FakeBin) -> subprocess.CompletedProcess[str]:
        return fake_bin.run_shell_env(args=[BASH, str(INSTALL_SH), "--finalize-environment"])

    def test_writes_managed_file_and_profiles_without_installing(self, fake_bin: FakeBin) -> None:
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        for tool in ("brew", "git", "apt-get", "pyenv", "sudo"):
            fake_bin.add(name=tool)
        result = self._run(fake_bin)
        assert result.returncode == 0, result.stderr
        assert str(location / "skills") in fake_bin.managed_env_file.read_text()
        for name, path in fake_bin.profile_paths.items():
            assert marker_pair_count(text=path.read_text()) == 1, name
        assert fake_bin.calls == ["pipx runpip slo show slo"]

    def test_fails_without_writing_when_the_package_cannot_be_located(self, fake_bin: FakeBin) -> None:
        fake_bin.write_fake_pipx(location=None)
        result = self._run(fake_bin)
        assert result.returncode != 0
        assert not fake_bin.managed_env_file.exists()
        for path in fake_bin.profile_paths.values():
            assert not path.exists()

    def test_rerun_is_idempotent(self, fake_bin: FakeBin) -> None:
        fake_bin.write_fake_pipx(location=fake_bin.make_package_location())
        assert self._run(fake_bin).returncode == 0
        snapshot: dict[str, bytes] = {n: p.read_bytes() for n, p in fake_bin.profile_paths.items()}
        managed: bytes = fake_bin.managed_env_file.read_bytes()
        assert self._run(fake_bin).returncode == 0
        assert {n: p.read_bytes() for n, p in fake_bin.profile_paths.items()} == snapshot
        assert fake_bin.managed_env_file.read_bytes() == managed


class TestSourcingGuard:
    """Sourcing install.sh must not run `main` (so tests can call functions)."""

    def test_sourcing_runs_nothing(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(snippet=":")
        assert result.returncode == 0
        assert fake_bin.calls == []
