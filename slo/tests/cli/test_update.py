"""Unit tests for ``src.cli.update`` — the pipx-VCS self-updater.

The ``Updater`` reinstalls slo via ``pipx install --force
"git+<url>@<ref>#subdirectory=slo"``, mirroring ``install.sh``. These tests
patch ``subprocess.run`` / ``shutil.which`` so no real git, pipx, pyenv, or
network is touched, and assert on the exact ref resolution, requirement spec,
auth-URL injection, interpreter resolution, and uv-backend fallback.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.cli.update import Updater, main


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    """Build a ``CompletedProcess`` stand-in for a patched ``subprocess.run``."""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestPipxSpec:
    """``_pipx_spec`` targets the slo/ subdirectory at the given ref."""

    def test_spec_ignores_legacy_repository_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_USERNAME", "legacy-user")
        monkeypatch.setenv("SLO_TOKEN", "legacy-token")
        monkeypatch.setenv("SLO_DEPLOY_TOKEN_USERNAME", "deploy-user")
        monkeypatch.setenv("SLO_DEPLOY_TOKEN", "deploy-token")
        monkeypatch.setenv("SLO_INSTALL_TOKEN", "pat-token")
        spec = Updater._pipx_spec(ref="v0.3.2")
        assert spec == "git+https://gitlab.com/core-27/slo.git@v0.3.2#subdirectory=slo"
        assert "legacy-token" not in spec
        assert "deploy-token" not in spec
        assert "pat-token" not in spec


class TestResolveLatestReleaseTag:
    """``resolve_latest_release_tag`` picks the highest vX.Y.Z from ls-remote."""

    _LS_REMOTE = (
        "abc\trefs/tags/v0.2.0\n"
        "def\trefs/tags/v0.10.1\n"  # numeric, not lexical, ordering
        "ghi\trefs/tags/v0.3.2\n"
        "jkl\trefs/tags/not-a-version\n"
        "mno\trefs/tags/v0.10.0\n"
    )

    def test_picks_highest_semver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SLO_USERNAME", raising=False)
        monkeypatch.delenv("SLO_TOKEN", raising=False)
        with patch("src.cli.update.subprocess.run", return_value=_completed(stdout=self._LS_REMOTE)) as run:
            assert Updater.resolve_latest_release_tag() == "v0.10.1"
        # ls-remote invoked against the (clean) auth URL
        assert run.call_args.args[0][:3] == ["git", "ls-remote", "--tags"]

    def test_no_version_tags_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SLO_USERNAME", raising=False)
        monkeypatch.delenv("SLO_TOKEN", raising=False)
        with patch(
            "src.cli.update.subprocess.run", return_value=_completed(stdout="zzz\trefs/tags/nightly\n")
        ):
            with pytest.raises(SystemExit):
                Updater.resolve_latest_release_tag()


class TestUvFallback:
    """``_uv_present_but_broken`` only triggers when uv is on PATH but won't run."""

    def test_absent_uv_is_not_broken(self) -> None:
        with patch("src.cli.update.shutil.which", return_value=None):
            assert Updater._uv_present_but_broken() is False

    def test_present_runnable_uv_is_not_broken(self) -> None:
        with (
            patch("src.cli.update.shutil.which", return_value="/x/uv"),
            patch("src.cli.update.subprocess.run", return_value=_completed(stdout="uv 0.5.0")),
        ):
            assert Updater._uv_present_but_broken() is False

    def test_present_failing_uv_is_broken(self) -> None:
        with (
            patch("src.cli.update.shutil.which", return_value="/x/uv"),
            patch("src.cli.update.subprocess.run", return_value=_completed(returncode=127)),
        ):
            assert Updater._uv_present_but_broken() is True


class TestPythonBin:
    """``_python_bin`` prefers the concrete pyenv interpreter over the shim."""

    def test_uses_concrete_pyenv_interpreter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYENV_ROOT", str(tmp_path))
        interp = tmp_path / "versions" / "3.11.7" / "bin" / "python3.11"
        interp.parent.mkdir(parents=True)
        interp.write_text("#!/bin/sh\n")
        interp.chmod(0o755)
        assert Updater._python_bin() == str(interp)

    def test_falls_back_to_path_python311(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYENV_ROOT", str(tmp_path))  # no versions dir -> miss
        with patch("src.cli.update.shutil.which", return_value="/usr/bin/python3.11"):
            assert Updater._python_bin() == "/usr/bin/python3.11"


class TestPipxInstall:
    """``_pipx_install`` builds the pipx command and forces pip off a broken uv."""

    def test_builds_force_install_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PIPX_DEFAULT_BACKEND", raising=False)
        with (
            patch("src.cli.update.Updater._python_bin", return_value="/py/python3.11"),
            patch("src.cli.update.Updater._uv_present_but_broken", return_value=False),
            patch("src.cli.update.subprocess.run") as run,
        ):
            Updater._pipx_install(spec="git+https://x/slo.git@main#subdirectory=slo")
        cmd = run.call_args.args[0]
        assert cmd == [
            "pipx",
            "install",
            "--force",
            "--python",
            "/py/python3.11",
            "git+https://x/slo.git@main#subdirectory=slo",
        ]
        assert run.call_args.kwargs["env"].get("PIPX_DEFAULT_BACKEND") is None

    def test_forces_pip_backend_when_uv_broken(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PIPX_DEFAULT_BACKEND", raising=False)
        with (
            patch("src.cli.update.Updater._python_bin", return_value="/py/python3.11"),
            patch("src.cli.update.Updater._uv_present_but_broken", return_value=True),
            patch("src.cli.update.subprocess.run") as run,
        ):
            Updater._pipx_install(spec="spec")
        assert run.call_args.kwargs["env"]["PIPX_DEFAULT_BACKEND"] == "pip"

    def test_respects_caller_pinned_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PIPX_DEFAULT_BACKEND", "uv")
        with (
            patch("src.cli.update.Updater._python_bin", return_value="/py/python3.11"),
            patch("src.cli.update.Updater._uv_present_but_broken", return_value=True),
            patch("src.cli.update.subprocess.run") as run,
        ):
            Updater._pipx_install(spec="spec")
        assert run.call_args.kwargs["env"]["PIPX_DEFAULT_BACKEND"] == "uv"


class TestInvoke:
    """``invoke`` resolves the right ref per mode and installs it."""

    def _patched(self) -> tuple[MagicMock, MagicMock, MagicMock]:
        return (
            patch("src.cli.update.Updater._pipx_install"),
            patch("src.cli.update.Updater.resolve_latest_release_tag", return_value="v9.9.9"),
            patch("src.cli.update.Updater._pipx_spec", side_effect=lambda *, ref: f"spec@{ref}"),
        )

    def test_default_installs_latest_release(self) -> None:
        p_install, p_resolve, p_spec = self._patched()
        with p_install as install, p_resolve as resolve, p_spec:
            Updater.invoke()
        resolve.assert_called_once_with()
        install.assert_called_once_with(spec="spec@v9.9.9")

    def test_development_installs_main(self) -> None:
        p_install, p_resolve, p_spec = self._patched()
        with p_install as install, p_resolve as resolve, p_spec:
            Updater.invoke(development=True)
        resolve.assert_not_called()
        install.assert_called_once_with(spec="spec@main")

    def test_explicit_ref_overrides_everything(self) -> None:
        p_install, p_resolve, p_spec = self._patched()
        with p_install as install, p_resolve as resolve, p_spec:
            Updater.invoke(development=True, ref="abc123")
        resolve.assert_not_called()
        install.assert_called_once_with(spec="spec@abc123")


class TestMain:
    """``main`` maps argv to ``Updater.invoke`` kwargs."""

    @pytest.mark.parametrize(
        "argv, expected",
        [
            ([], {"development": False, "ref": None}),
            (["--development"], {"development": True, "ref": None}),
            (["--ref", "v1.2.3"], {"development": False, "ref": "v1.2.3"}),
        ],
    )
    def test_argv_maps_to_invoke(self, argv: list[str], expected: dict[str, Optional[str]]) -> None:
        with patch("src.cli.update.Updater.invoke") as invoke:
            assert main(argv) == 0
        invoke.assert_called_once_with(**expected)

    def test_development_and_ref_are_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            main(["--development", "--ref", "v1.2.3"])


class TestUpdateIsNotAnEnvironmentWriter:
    """M2 (spec 80.a.2): ``slo update`` is pipx-only, never a shell writer.

    The updater deliberately does NOT refresh the installer-managed environment
    file or any profile source block: there is exactly one owner of persistent
    shell defaults (``install.sh`` finalisation). If a pipx reinstall changes
    the distribution Location, the documented recovery is rerunning the public
    installer, whose finalisation refreshes the managed file atomically.
    """

    def test_invoke_never_touches_the_managed_environment_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A full update writes nothing under the managed shell file path."""
        home: Path = tmp_path / "home"
        managed_file: Path = home / ".slo" / "shell" / "environment.sh"
        managed_file.parent.mkdir(parents=True)
        managed_file.write_text("# existing managed content\n")
        before: bytes = managed_file.read_bytes()
        monkeypatch.setenv("HOME", str(home))
        with patch("src.cli.update.Updater._pipx_install") as install:
            Updater.invoke(ref="v9.9.9")
        install.assert_called_once()
        assert managed_file.read_bytes() == before

    def test_invoke_never_touches_shell_profiles(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A full update edits no shell startup file in the user's home."""
        home: Path = tmp_path / "home"
        home.mkdir()
        profiles: dict[str, Path] = {
            name: home / name for name in (".bash_profile", ".bashrc", ".zshenv", ".profile")
        }
        for name, profile in profiles.items():
            profile.write_text(f"# {name} user content\n")
        before: dict[str, bytes] = {name: path.read_bytes() for name, path in profiles.items()}
        monkeypatch.setenv("HOME", str(home))
        with patch("src.cli.update.Updater._pipx_install"):
            Updater.invoke(ref="v9.9.9")
        for name, profile in profiles.items():
            assert profile.read_bytes() == before[name], name


class TestCheckPathAfterInstall:
    """``_check_path_after_install`` warns when ``~/.local/bin`` is off PATH."""

    def test_silent_when_local_bin_on_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No output when ~/.local/bin is already on PATH."""
        from pathlib import Path

        local_bin = str(Path.home() / ".local" / "bin")
        monkeypatch.setenv("PATH", f"{local_bin}:/usr/bin:/bin")
        Updater._check_path_after_install()
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_warns_when_local_bin_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Warning text appears on stderr when ~/.local/bin is absent from PATH."""
        monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/local/bin")
        Updater._check_path_after_install()
        captured = capsys.readouterr()
        assert "~/.local/bin is not on your PATH" in captured.err
        assert "~/.zshrc" in captured.err
        assert "pipx ensurepath" in captured.err
