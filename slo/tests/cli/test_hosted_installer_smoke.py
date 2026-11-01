"""Opt-in end-to-end proof for the published tagged installer artifact."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pytest


@dataclass(frozen=True)
class HostedInstallerSmokeConfig:
    """Immutable input contract for a disposable hosted-installer product smoke."""

    release_tag: str
    install_url: str


def _hosted_smoke_config() -> HostedInstallerSmokeConfig:
    """Validate release inputs before downloading or executing a hosted artifact.

    Returns:
        HostedInstallerSmokeConfig: Immutable tag and HTTPS installer source.

    Raises:
        ValueError: If the explicit release evidence inputs are unsafe or absent.
    """
    release_tag: str = os.environ.get("SLO_RELEASE_TAG", "")
    install_url: str = os.environ.get("SLO_INSTALL_URL", "")
    platform_smoke: str = os.environ.get("SLO_PLATFORM_SMOKE", "")
    parsed_url = urlparse(install_url)
    if not release_tag.startswith("v") or release_tag == "v":
        raise ValueError("SLO_RELEASE_TAG must be an explicit immutable v-prefixed tag")
    if (
        parsed_url.scheme != "https"
        or not parsed_url.netloc
        or parsed_url.hostname in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("SLO_INSTALL_URL must be a non-local HTTPS hosted installer URL")
    if platform_smoke == "macos" and sys.platform != "darwin":
        raise ValueError("SLO_PLATFORM_SMOKE=macos requires a Darwin runner")
    return HostedInstallerSmokeConfig(release_tag=release_tag, install_url=install_url)


def _hosted_smoke_environment(*, root: Path) -> dict[str, str]:
    """Build a disposable installer environment while retaining required host tools.

    Args:
        root: Temporary root that owns HOME and all pipx state for this run.

    Returns:
        dict[str, str]: Environment suitable for executing the downloaded script.
    """
    environment: dict[str, str] = dict(os.environ)
    environment.update(
        {
            "HOME": str(root / "home"),
            "PIPX_HOME": str(root / "pipx-home"),
            "PIPX_BIN_DIR": str(root / "pipx-bin"),
            "PIPX_SHARED_LIBS": str(root / "pipx-shared"),
            "SLO_HOME": str(root / "slo-home"),
            "PATH": f"{root / 'pipx-bin'}{os.pathsep}{environment.get('PATH', '')}",
        }
    )
    return environment


def _run(*, argv: list[str], environment: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one smoke command and preserve its output for an assertion failure.

    Args:
        argv: Exact executable argument vector.
        environment: Disposable process environment.
        cwd: Temporary current directory.

    Returns:
        subprocess.CompletedProcess[str]: Completed command result.
    """
    return subprocess.run(
        argv, cwd=cwd, env=environment, capture_output=True, text=True, check=False, timeout=1800
    )


@pytest.mark.e2e
@pytest.mark.skipif(
    os.environ.get("SLO_DIRECT_PIPX_RECOVERY_E2E") != "1",
    reason="opt-in only: set SLO_DIRECT_PIPX_RECOVERY_E2E=1 for a disposable local-wheel recovery proof",
)
@pytest.mark.parametrize("backend", ["pip", "uv"])
def test_direct_pipx_regeneration_recovers_through_packaged_finalizer(tmp_path: Path, backend: str) -> None:
    """Recover real wheel scripts for each backend without modifying the owned entry.

    Args:
        tmp_path: Sole writable installation root.
        backend: Explicit modern pipx backend; legacy pipx only supports pip.
    """
    wheel_path: str = os.environ.get("SLO_LOCAL_WHEEL", "")
    wheel: Path = Path(wheel_path).resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        pytest.fail("SLO_LOCAL_WHEEL must name a built local Slo wheel")
    pipx: str | None = shutil.which("pipx")
    if pipx is None:
        pytest.fail("direct pipx recovery proof requires a real pipx executable on PATH")

    root: Path = tmp_path / "direct-pipx-recovery"
    root.mkdir()
    environment: dict[str, str] = _hosted_smoke_environment(root=root)
    environment["PIPX_DEFAULT_BACKEND"] = backend
    install: subprocess.CompletedProcess[str] = _run(
        argv=[pipx, "install", "--force", str(wheel)], environment=environment, cwd=root
    )
    assert install.returncode == 0, install.stderr

    venv_bin: Path = root / "pipx-home" / "venvs" / "slo" / "bin"
    wrapper: Path = venv_bin / "slo"
    assert b"slo isolated launcher" not in wrapper.read_bytes()
    regenerate: subprocess.CompletedProcess[str] = _run(
        argv=[pipx, "reinstall", "slo"], environment=environment, cwd=root
    )
    assert regenerate.returncode == 0, regenerate.stderr
    assert b"slo isolated launcher" not in wrapper.read_bytes()
    entry: Path = venv_bin / "slo-entry"
    entry_before: bytes = entry.read_bytes()
    metadata: Path = venv_bin.parent / "pipx_metadata.json"
    # New pipx records its actual backend. An env value alone does not prove it.
    installed_backend: str = json.loads(metadata.read_text()).get("backend", "pip")
    assert installed_backend == backend

    installed_script: subprocess.CompletedProcess[str] = _run(
        argv=[pipx, "runpip", "slo", "show", "slo"], environment=environment, cwd=root
    )
    assert installed_script.returncode == 0, installed_script.stderr
    location_line: str = next(
        (line for line in installed_script.stdout.splitlines() if line.startswith("Location: ")), ""
    )
    assert location_line
    finalizer: Path = Path(location_line.removeprefix("Location: ")) / "install.sh"
    assert finalizer.is_file()
    finalize: subprocess.CompletedProcess[str] = _run(
        argv=["bash", str(finalizer), "--finalize-launcher"], environment=environment, cwd=root
    )
    assert finalize.returncode == 0, finalize.stderr
    assert b"slo isolated launcher" in wrapper.read_bytes()
    assert entry.read_bytes() == entry_before

    hostile_root: Path = root / "hostile"
    (hostile_root / "src").mkdir(parents=True)
    (hostile_root / "src" / "cli.py").write_text("raise RuntimeError('hostile src selected')\n")
    invocation: subprocess.CompletedProcess[str] = _run(
        argv=[str(wrapper), "--help"],
        environment=environment | {"PYTHONPATH": str(hostile_root)},
        cwd=hostile_root,
    )
    assert invocation.returncode == 0, invocation.stderr


@pytest.mark.e2e
@pytest.mark.skipif(
    os.environ.get("SLO_HOSTED_INSTALL_E2E") != "1",
    reason="opt-in only: set SLO_HOSTED_INSTALL_E2E=1 after tagged publication",
)
def test_hosted_installer_installs_and_runs_the_tagged_product(tmp_path: Path) -> None:
    """Download, install, finalize, and execute the hosted tagged product in disposable roots.

    Args:
        tmp_path: Per-test root for the downloaded installer and pipx installation.
    """
    config: HostedInstallerSmokeConfig = _hosted_smoke_config()
    if shutil.which("pipx") is None:
        pytest.fail("hosted installer smoke requires a real pipx executable on PATH")

    root: Path = tmp_path / "hosted-smoke"
    root.mkdir()
    fetched_script: Path = root / "install.sh"
    environment: dict[str, str] = _hosted_smoke_environment(root=root)
    curl: subprocess.CompletedProcess[str] = _run(
        argv=["curl", "-fsSL", config.install_url, "-o", str(fetched_script)],
        environment=environment,
        cwd=root,
    )
    assert curl.returncode == 0, curl.stderr
    script_bytes: bytes = fetched_script.read_bytes()
    assert script_bytes.startswith(b"#!")
    assert f'SLO_REF="${{SLO_REF:-{config.release_tag}}}"'.encode() in script_bytes

    install: subprocess.CompletedProcess[str] = _run(
        argv=["bash", str(fetched_script)], environment=environment, cwd=root
    )
    assert install.returncode == 0, install.stderr

    venv_bin: Path = root / "pipx-home" / "venvs" / "slo" / "bin"
    wrapper: Path = venv_bin / "slo"
    entry: Path = venv_bin / "slo-entry"
    assert wrapper.is_file() and not wrapper.is_symlink()
    assert entry.is_file() and not entry.is_symlink()
    wrapper_bytes: bytes = wrapper.read_bytes()
    assert b"# >>> slo isolated launcher (v1) >>>" in wrapper_bytes
    assert b" -I " in wrapper_bytes
    assert str(entry).encode() in wrapper_bytes

    hostile_root: Path = root / "hostile"
    (hostile_root / "src").mkdir(parents=True)
    (hostile_root / "src" / "cli.py").write_text("raise RuntimeError('hostile src selected')\n")
    hostile_environment: dict[str, str] = environment | {"PYTHONPATH": str(hostile_root)}
    invocation: subprocess.CompletedProcess[str] = _run(
        argv=[str(wrapper), "--help"], environment=hostile_environment, cwd=hostile_root
    )
    assert invocation.returncode == 0, invocation.stderr


def test_hosted_smoke_environment_uses_disposable_roots_and_retains_path(tmp_path: Path) -> None:
    """Runner construction isolates writable state without dropping pipx discovery."""
    environment: dict[str, str] = _hosted_smoke_environment(root=tmp_path)

    assert environment["HOME"] == str(tmp_path / "home")
    assert environment["PIPX_HOME"] == str(tmp_path / "pipx-home")
    assert environment["PIPX_BIN_DIR"] == str(tmp_path / "pipx-bin")
    assert environment["SLO_HOME"] == str(tmp_path / "slo-home")
    assert environment["PATH"].startswith(f"{tmp_path / 'pipx-bin'}{os.pathsep}")


def test_direct_pipx_recovery_flow_is_opt_in_and_uses_only_disposable_roots() -> None:
    """The guarded product flow records install, regeneration, finalization, and hostile proof steps."""
    source: str = Path(__file__).read_text()

    assert "SLO_DIRECT_PIPX_RECOVERY_E2E" in source
    assert '"install", "--force"' in source
    assert '"reinstall", "slo"' in source
    assert "--finalize-launcher" in source
    assert "hostile" in source
    assert '"PIPX_HOME": str(root / "pipx-home")' in source


@pytest.mark.parametrize(
    "release_tag, install_url",
    [("", "https://get-slo.sh/install.sh"), ("v1.2.3", "http://get-slo.sh/install.sh")],
)
def test_hosted_smoke_config_rejects_non_release_inputs(
    monkeypatch: pytest.MonkeyPatch, release_tag: str, install_url: str
) -> None:
    """Hosted runner refuses missing tags and non-HTTPS/local sources before any product action."""
    monkeypatch.setenv("SLO_RELEASE_TAG", release_tag)
    monkeypatch.setenv("SLO_INSTALL_URL", install_url)

    with pytest.raises(ValueError):
        _hosted_smoke_config()
