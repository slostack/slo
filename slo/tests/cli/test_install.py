"""Unit tests for ``install.sh`` — the self-bootstrapping installer.

Each test sources ``install.sh`` in a bash subprocess with a stubbed ``PATH`` so the
installer's decision points are exercised without mutating the host (no real
brew / pyenv / pipx / git / network). Fake executables log their invocations to a
call log the tests assert on. ``install.sh`` only runs ``main`` when executed
directly, so sourcing it exposes every function for isolated testing.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

INSTALL_SH: Path = Path(__file__).resolve().parents[2] / "install.sh"
BASH: str = shutil.which("bash") or "/bin/bash"


class FakeBin:
    """A throwaway PATH directory of fake executables that log their invocations.

    Tests opt tools in (present) or leave them out (absent) to drive the
    installer's ``command -v`` branches. ``uname`` is special-cased to echo a
    chosen kernel name so OS detection can be exercised on any host.
    """

    def __init__(self, *, root: Path) -> None:
        """Create the fake bin dir, call log, and a real ``mkdir`` the installer needs.

        Args:
            root (Path): Temp root for the bin dir, call log, and fake HOME.
        """
        self._root: Path = root
        self._bin: Path = root / "bin"
        self._bin.mkdir(parents=True, exist_ok=True)
        self._home: Path = root / "home"
        self._home.mkdir(parents=True, exist_ok=True)
        self._log: Path = root / "calls.log"
        self._log.write_text("")
        self._os_release: Path | None = None
        self._symlink_real(name="mkdir")

    def _symlink_real(self, *, name: str) -> None:
        """Symlink a real system executable into the fake bin (e.g. ``mkdir``).

        Args:
            name (str): Executable to resolve on the host and link in.
        """
        real: str | None = shutil.which(name)
        assert real is not None, f"{name} must exist on the host for the harness"
        (self._bin / name).symlink_to(real)

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
        full_env: dict[str, str] = {
            "PATH": str(self._bin),
            "HOME": str(self._home),
            "SLO_CALL_LOG": str(self._log),
        }
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
            '  exit 1\n'
            'fi\n'
            'exit 0\n'
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

    def test_resolves_concrete_interpreter_when_pyenv_present(self, fake_bin: FakeBin, tmp_path: Path) -> None:
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

    def test_injects_token_for_private_https(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install", env={"SLO_INSTALL_TOKEN": "glpat-secret"})
        assert any(
            "git+https://oauth2:glpat-secret@gitlab.com/core-27/slo.git@main" in c
            for c in fake_bin.calls
        )

    def test_no_token_leaves_url_clean(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install")
        assert not any("oauth2:" in c for c in fake_bin.calls)

    def test_injects_deploy_token_username_and_password(self, fake_bin: FakeBin) -> None:
        # A GitLab deploy token authenticates as <username>:<token>, not oauth2.
        fake_bin.add(name="pipx")
        fake_bin.run(
            snippet="slo_install",
            env={"SLO_DEPLOY_TOKEN_USERNAME": "gitlab+deploy-token-7", "SLO_DEPLOY_TOKEN": "dt-secret"},
        )
        assert any(
            "git+https://gitlab+deploy-token-7:dt-secret@gitlab.com/core-27/slo.git@main" in c
            for c in fake_bin.calls
        )
        assert not any("oauth2:" in c for c in fake_bin.calls)

    def test_deploy_token_takes_precedence_over_pat(self, fake_bin: FakeBin) -> None:
        fake_bin.add(name="pipx")
        fake_bin.run(
            snippet="slo_install",
            env={
                "SLO_DEPLOY_TOKEN_USERNAME": "dt-user",
                "SLO_DEPLOY_TOKEN": "dt-secret",
                "SLO_INSTALL_TOKEN": "glpat-secret",
            },
        )
        assert any("https://dt-user:dt-secret@" in c for c in fake_bin.calls)
        assert not any("oauth2:" in c for c in fake_bin.calls)

    def test_deploy_token_username_without_password_is_ignored(self, fake_bin: FakeBin) -> None:
        # A half-configured deploy token must not produce a malformed URL.
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install", env={"SLO_DEPLOY_TOKEN_USERNAME": "dt-user"})
        assert any("git+https://gitlab.com/core-27/slo.git@main" in c for c in fake_bin.calls)
        assert not any("dt-user" in c for c in fake_bin.calls)

    def test_targets_slo_subdirectory(self, fake_bin: FakeBin) -> None:
        # The project lives in the repo's slo/ subdir, so pip must be told where
        # pyproject.toml is via the #subdirectory fragment.
        fake_bin.add(name="pipx")
        fake_bin.run(snippet="slo_install")
        assert any("git+https://gitlab.com/core-27/slo.git@main#subdirectory=slo" in c for c in fake_bin.calls)

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


class TestSourcingGuard:
    """Sourcing install.sh must not run `main` (so tests can call functions)."""

    def test_sourcing_runs_nothing(self, fake_bin: FakeBin) -> None:
        result = fake_bin.run(snippet=":")
        assert result.returncode == 0
        assert fake_bin.calls == []
