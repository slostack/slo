"""Unit tests for ``src.cli.update`` — the pipx-VCS self-updater.

The ``Updater`` reinstalls slo via ``pipx install --force
"git+<url>@<ref>#subdirectory=slo"``, mirroring ``install.sh``. These tests
patch ``subprocess.run`` / ``shutil.which`` so no real git, pipx, pyenv, or
network is touched, and assert on the exact ref resolution, requirement spec,
auth-URL injection, interpreter resolution, and uv-backend fallback.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Generator, Optional
from unittest.mock import MagicMock, _patch, patch

import pytest

from src.cli.update import ShellEnvironmentDefaults, Updater, main

INSTALL_SH: Path = Path(__file__).resolve().parents[2] / "install.sh"
BASH: str = shutil.which("bash") or "/bin/bash"
SLO_VARS: tuple[str, ...] = ("SLO_HOME", "SLO_SKILLS_DIR", "SLO_KB_DIR", "KB_DIR")


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

    @pytest.fixture(autouse=True)
    def _no_finalization_steps(self) -> Generator[None, None, None]:
        with (
            patch("src.cli.update.ShellEnvironmentDefaults.finalize_launcher"),
            patch("src.cli.update.ShellEnvironmentDefaults.ensure"),
        ):
            yield

    def _patched(self) -> tuple[_patch, _patch, _patch]:
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


class TestUpdateLauncherFinalization:
    """Updates harden regenerated scripts before touching shell defaults."""

    def test_runs_launcher_finalizer_before_environment_defaults(self) -> None:
        """Successful pipx install sequences pipx, launcher finalizer, then environment defaults."""
        order: list[str] = []
        with (
            patch("src.cli.update.Updater._pipx_install", side_effect=lambda *, spec: order.append("pipx")),
            patch(
                "src.cli.update.ShellEnvironmentDefaults.finalize_launcher",
                side_effect=lambda: order.append("launcher"),
            ),
            patch(
                "src.cli.update.ShellEnvironmentDefaults.ensure",
                side_effect=lambda *, environ: order.append("environment"),
            ),
        ):
            Updater.invoke(ref="v9.9.9")

        assert order == ["pipx", "launcher", "environment"]

    def test_launcher_failure_stops_before_environment_defaults(self) -> None:
        """Failed hardening leaves shell defaults untouched after a code reinstall."""
        with (
            patch("src.cli.update.Updater._pipx_install"),
            patch(
                "src.cli.update.ShellEnvironmentDefaults.finalize_launcher",
                side_effect=SystemExit("launcher failed"),
            ),
            patch("src.cli.update.ShellEnvironmentDefaults.ensure") as ensure,
        ):
            with pytest.raises(SystemExit, match="launcher failed"):
                Updater.invoke(ref="v9.9.9")
        ensure.assert_not_called()


class TestInvokeEnsuresEnvironmentDefaults:
    """Every update mode sets missing environment defaults, and only after pipx succeeds."""

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"development": True}, {"ref": "feature-x"}],
        ids=["release", "development", "ref"],
    )
    def test_runs_after_a_successful_install(self, kwargs: dict[str, object]) -> None:
        order: list[str] = []
        with (
            patch("src.cli.update.Updater.resolve_latest_release_tag", return_value="v9.9.9"),
            patch("src.cli.update.Updater._pipx_install", side_effect=lambda *, spec: order.append("pipx")),
            patch(
                "src.cli.update.ShellEnvironmentDefaults.finalize_launcher",
                side_effect=lambda: order.append("launcher"),
            ),
            patch(
                "src.cli.update.ShellEnvironmentDefaults.ensure",
                side_effect=lambda *, environ: order.append("environment"),
            ) as ensure,
        ):
            Updater.invoke(**kwargs)  # type: ignore[arg-type]
        assert order == ["pipx", "launcher", "environment"]
        assert ensure.call_args.kwargs["environ"] is os.environ

    def test_is_skipped_when_pipx_fails(self) -> None:
        with (
            patch(
                "src.cli.update.Updater._pipx_install",
                side_effect=subprocess.CalledProcessError(returncode=1, cmd=["pipx"]),
            ),
            patch("src.cli.update.ShellEnvironmentDefaults.finalize_launcher") as launcher,
            patch("src.cli.update.ShellEnvironmentDefaults.ensure") as ensure,
        ):
            with pytest.raises(subprocess.CalledProcessError):
                Updater.invoke(ref="v9.9.9")
        launcher.assert_not_called()
        ensure.assert_not_called()


class TestMissingEnvironmentDefaults:
    """``missing`` decides by existence; ``KB_DIR`` stands in for ``SLO_KB_DIR``."""

    def test_all_missing(self) -> None:
        assert ShellEnvironmentDefaults.missing(environ={}) == ["SLO_HOME", "SLO_SKILLS_DIR", "SLO_KB_DIR"]

    def test_kb_dir_counts_as_slo_kb_dir(self) -> None:
        environ: dict[str, str] = {"SLO_HOME": "/h", "SLO_SKILLS_DIR": "/s", "KB_DIR": "/k"}
        assert ShellEnvironmentDefaults.missing(environ=environ) == []

    def test_set_but_empty_counts_as_present(self) -> None:
        environ: dict[str, str] = {"SLO_HOME": "", "SLO_SKILLS_DIR": "", "SLO_KB_DIR": ""}
        assert ShellEnvironmentDefaults.missing(environ=environ) == []

    def test_reports_only_what_is_missing(self) -> None:
        assert ShellEnvironmentDefaults.missing(environ={"SLO_HOME": "/h", "SLO_KB_DIR": "/k"}) == [
            "SLO_SKILLS_DIR"
        ]


class TestInstalledLocation:
    """``installed_location`` reads pip metadata exactly like install.sh."""

    def test_returns_the_single_location(self) -> None:
        with patch("subprocess.run", return_value=_completed("Name: slo\nLocation: /pkgs/site\n")):
            assert ShellEnvironmentDefaults.installed_location() == Path("/pkgs/site")

    @pytest.mark.parametrize(
        "stdout",
        ["Name: slo\n", "Location: /a\nLocation: /b\n"],
        ids=["no-location", "ambiguous"],
    )
    def test_returns_none_when_metadata_is_unusable(self, stdout: str) -> None:
        with patch("subprocess.run", return_value=_completed(stdout)):
            assert ShellEnvironmentDefaults.installed_location() is None

    def test_returns_none_when_pipx_fails(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["pipx"])):
            assert ShellEnvironmentDefaults.installed_location() is None

    def test_returns_none_when_pipx_is_absent(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("pipx")):
            assert ShellEnvironmentDefaults.installed_location() is None


def _package_location(root: Path, *, with_installer: bool = True) -> Path:
    """Create a fake installed package: ``skills/INDEX.md`` plus a real ``install.sh`` copy."""
    location: Path = root / "site packages"
    (location / "skills").mkdir(parents=True)
    (location / "skills" / "INDEX.md").write_text("# index\n")
    if with_installer:
        shutil.copy(INSTALL_SH, location / "install.sh")
    return location


class TestLauncherFinalizer:
    """``finalize_launcher`` only delegates to the installed shell writer."""

    def test_uses_regular_installed_finalizer_with_exact_argv(self, tmp_path: Path) -> None:
        """The updater invokes the packaged launcher-only mode through Bash."""
        location: Path = _package_location(tmp_path)
        with (
            patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location),
            patch("src.cli.update.shutil.which", return_value="/verified/bash"),
            patch("src.cli.update.subprocess.run", return_value=_completed()) as run,
        ):
            ShellEnvironmentDefaults.finalize_launcher()

        assert run.call_args.args[0] == [
            "/verified/bash",
            str(location / "install.sh"),
            "--finalize-launcher",
        ]
        assert run.call_args.kwargs == {"check": True}

    @pytest.mark.parametrize("kind", ["missing", "symlink"])
    def test_refuses_missing_or_symlinked_installer_with_recovery_guidance(
        self, tmp_path: Path, kind: str
    ) -> None:
        """Location artifacts that cannot be trusted stop before a subprocess is spawned."""
        location: Path = _package_location(tmp_path, with_installer=kind != "missing")
        installer: Path = location / "install.sh"
        if kind == "symlink":
            target: Path = tmp_path / "external-installer"
            target.write_text("#!/bin/sh\\n")
            installer.unlink()
            installer.symlink_to(target)
        with (
            patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location),
            patch("src.cli.update.subprocess.run") as run,
        ):
            with pytest.raises(SystemExit) as raised:
                ShellEnvironmentDefaults.finalize_launcher()
        assert "launcher was not finalized" in str(raised.value)
        assert "matching tagged public installer" in str(raised.value)
        run.assert_not_called()

    def test_missing_location_includes_recovery_guidance(self) -> None:
        """Missing metadata is an updated-but-unfinalized failure, not a fallback guess."""
        with patch.object(ShellEnvironmentDefaults, "installed_location", return_value=None):
            with pytest.raises(SystemExit) as raised:
                ShellEnvironmentDefaults.finalize_launcher()
        assert "launcher was not finalized" in str(raised.value)
        assert "matching tagged public installer" in str(raised.value)

    @pytest.mark.parametrize(
        "error", [OSError("bash unavailable"), subprocess.CalledProcessError(1, ["bash"])]
    )
    def test_subprocess_failure_includes_recovery_guidance(
        self, tmp_path: Path, error: BaseException
    ) -> None:
        """The launcher failure boundary retains an actionable supported-repair instruction."""
        location: Path = _package_location(tmp_path)
        with (
            patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location),
            patch("src.cli.update.subprocess.run", side_effect=error),
        ):
            with pytest.raises(SystemExit) as raised:
                ShellEnvironmentDefaults.finalize_launcher()
        assert "launcher was not finalized" in str(raised.value)
        assert "matching tagged public installer" in str(raised.value)


class TestEnsureDecisions:
    """``ensure`` runs the installer step only when a variable is missing, and fails loudly."""

    def test_all_present_runs_nothing_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        location: Path = _package_location(tmp_path)
        environ: dict[str, str] = {
            "SLO_HOME": "/h",
            "SLO_SKILLS_DIR": str(location / "skills"),
            "SLO_KB_DIR": "/k",
        }
        with (
            patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location),
            patch("subprocess.run") as run,
        ):
            ShellEnvironmentDefaults.ensure(environ=environ)
        run.assert_not_called()
        err: str = capsys.readouterr().err
        assert "already set" in err
        assert "SLO_SKILLS_DIR" not in err.split("already set")[1]

    def test_missing_runs_the_installed_finalize_step(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        location: Path = _package_location(tmp_path)
        with (
            patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location),
            patch("subprocess.run", return_value=_completed()) as run,
        ):
            ShellEnvironmentDefaults.ensure(environ={"SLO_HOME": "/h"})
        command: list[str] = run.call_args.args[0]
        assert command[1:] == [str(location / "install.sh"), "--finalize-environment"]
        assert os.path.basename(command[0]) == "bash"
        assert run.call_args.kwargs["check"] is True
        assert "SLO_SKILLS_DIR, SLO_KB_DIR" in capsys.readouterr().err

    def test_missing_without_a_locatable_package_exits_non_zero(self) -> None:
        with patch.object(ShellEnvironmentDefaults, "installed_location", return_value=None):
            with pytest.raises(SystemExit) as raised:
                ShellEnvironmentDefaults.ensure(environ={})
        assert "slo was updated" in str(raised.value)
        assert "install.sh" in str(raised.value)

    def test_missing_installer_copy_exits_non_zero(self, tmp_path: Path) -> None:
        location: Path = _package_location(tmp_path, with_installer=False)
        with patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location):
            with pytest.raises(SystemExit) as raised:
                ShellEnvironmentDefaults.ensure(environ={})
        assert "install.sh" in str(raised.value)

    def test_finalize_failure_exits_non_zero(self, tmp_path: Path) -> None:
        location: Path = _package_location(tmp_path)
        with (
            patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location),
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, ["bash"])),
        ):
            with pytest.raises(SystemExit) as raised:
                ShellEnvironmentDefaults.ensure(environ={})
        assert "slo was updated" in str(raised.value)


class TestStaleSkillsDirWarning:
    """An existing ``SLO_SKILLS_DIR`` is never rewritten, but a wrong one is reported."""

    def _ensure(self, *, skills_dir: Path, location: Path | None) -> str:
        environ: dict[str, str] = {"SLO_HOME": "/h", "SLO_SKILLS_DIR": str(skills_dir), "SLO_KB_DIR": "/k"}
        with (
            patch.object(ShellEnvironmentDefaults, "installed_location", return_value=location),
            patch("subprocess.run") as run,
        ):
            ShellEnvironmentDefaults.ensure(environ=environ)
        run.assert_not_called()
        return self._capsys.readouterr().err

    @pytest.fixture(autouse=True)
    def _capture(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys

    def test_matching_path_is_quiet(self, tmp_path: Path) -> None:
        location: Path = _package_location(tmp_path)
        assert "warning" not in self._ensure(skills_dir=location / "skills", location=location)

    def test_path_without_index_is_a_warning(self, tmp_path: Path) -> None:
        location: Path = _package_location(tmp_path)
        err: str = self._ensure(skills_dir=tmp_path / "gone", location=location)
        assert "warning" in err
        assert "INDEX.md" in err
        assert str(location / "skills") in err

    def test_different_valid_path_is_a_note(self, tmp_path: Path) -> None:
        location: Path = _package_location(tmp_path)
        custom: Path = tmp_path / "dev checkout" / "skills"
        custom.mkdir(parents=True)
        (custom / "INDEX.md").write_text("# index\n")
        err: str = self._ensure(skills_dir=custom, location=location)
        assert "warning" not in err
        assert str(custom) in err
        assert str(location / "skills") in err


class TestEnsureEndToEnd:
    """Real bash runs the real install.sh copy against an isolated HOME and a fake pipx."""

    @pytest.fixture
    def isolated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
        home: Path = tmp_path / "home with ' quote"
        home.mkdir()
        location: Path = _package_location(tmp_path)
        bin_dir: Path = tmp_path / "bin"
        bin_dir.mkdir()
        pipx: Path = bin_dir / "pipx"
        pipx.write_text(
            "#!/bin/sh\n"
            'if [ "$*" = "runpip slo show slo" ]; then\n'
            '  echo "Name: slo"\n'
            f'  echo "Location: {location}"\n'
            "  exit 0\n"
            "fi\n"
            "exit 1\n"
        )
        pipx.chmod(0o755)
        for tool in ("chmod", "mv"):
            tool_path: Path = bin_dir / tool
            tool_path.write_text(f'#!/bin/sh\nexec /usr/bin/busybox {tool} "$@"\n')
            tool_path.chmod(0o755)
        mktemp: Path = bin_dir / "mktemp"
        mktemp.write_text(
            "#!/bin/sh\n"
            "path=$(printf '%s' \"$1\" | sed 's/XXXXXX/fixture/')\n"
            'touch "$path" && printf \'%s\\n\' "$path"\n'
        )
        mktemp.chmod(0o755)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        for name in SLO_VARS:
            monkeypatch.delenv(name, raising=False)
        return home, location

    def _login_shell_values(self, *, home: Path) -> list[str]:
        result = subprocess.run(
            [BASH, "--login", "-c", 'printf "%s\n%s\n%s\n" "$SLO_HOME" "$SLO_SKILLS_DIR" "$SLO_KB_DIR"'],
            env={"HOME": str(home), "PATH": os.environ["PATH"], "TERM": "dumb"},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.splitlines()

    def test_missing_variables_are_persisted_for_new_shells(self, isolated: tuple[Path, Path]) -> None:
        home, location = isolated
        ShellEnvironmentDefaults.ensure(environ=os.environ)
        assert (home / ".slo" / "shell" / "environment.sh").is_file()
        for profile in (".bash_profile", ".bashrc", ".zshenv", ".profile"):
            assert "slo managed environment" in (home / profile).read_text(), profile
        assert self._login_shell_values(home=home) == [
            f"{home}/.slo",
            os.path.realpath(location / "skills"),
            f"{home}/.slo/KnowledgeBase/KB",
        ]
        assert not (home / ".slo" / "KnowledgeBase").exists()

    def test_all_present_leaves_home_untouched(
        self, isolated: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home, location = isolated
        (home / ".bashrc").write_text("# user bashrc\n")
        monkeypatch.setenv("SLO_HOME", str(home / ".slo"))
        monkeypatch.setenv("SLO_SKILLS_DIR", str(location / "skills"))
        monkeypatch.setenv("KB_DIR", str(home / "kb"))
        ShellEnvironmentDefaults.ensure(environ=os.environ)
        assert sorted(p.name for p in home.iterdir()) == [".bashrc"]
        assert (home / ".bashrc").read_text() == "# user bashrc\n"

    def test_rerun_is_idempotent(self, isolated: tuple[Path, Path]) -> None:
        home, _ = isolated
        ShellEnvironmentDefaults.ensure(environ=os.environ)
        snapshot: dict[str, bytes] = {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()}
        ShellEnvironmentDefaults.ensure(environ=os.environ)
        assert {p.name: p.read_bytes() for p in home.iterdir() if p.is_file()} == snapshot


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
