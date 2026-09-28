"""Black-box contracts for the installer-owned isolated launcher finalizer."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.cli.test_install import FakeBin


class TestIsolatedLauncherLayoutResolver:
    """Validate portable pipx layout discovery without touching a real pipx root."""

    def _resolve(self, *, fake_bin: FakeBin) -> str:
        """Run the layout resolver through the sourced installer.

        Args:
            fake_bin (FakeBin): Isolated shell and pipx fixture.

        Returns:
            str: Resolver stdout containing the four machine-readable fields.
        """
        result = fake_bin.run(snippet="slo_resolve_isolated_launcher_layout")
        assert result.returncode == 0, result.stderr
        return result.stdout

    @pytest.mark.parametrize(
        "path_parts",
        [
            ("home", "linux", ".local", "share", "pipx"),
            ("Users", "operator", "Library", "Application Support", "pipx"),
        ],
    )
    def test_resolves_valid_platform_layout(self, tmp_path: Path, path_parts: tuple[str, ...]) -> None:
        """Linux- and macOS-shaped absolute roots resolve from the pipx API."""
        fake_bin = FakeBin(root=tmp_path / "fixture")
        pipx_home: Path = tmp_path.joinpath(*path_parts)
        venv_root, python_bin, user_launcher, entry_launcher = fake_bin.make_launcher_layout(
            pipx_home=pipx_home
        )
        location: Path = venv_root / "lib" / "python3.11" / "site-packages"
        location.mkdir(parents=True)
        fake_bin.write_fake_pipx(location=location, pipx_home=pipx_home)

        output = self._resolve(fake_bin=fake_bin)

        assert output.splitlines() == [
            f"venv_root={venv_root}",
            f"python_bin={python_bin}",
            f"user_launcher={user_launcher}",
            f"entry_launcher={entry_launcher}",
        ]

    def test_rejects_failed_pipx_home_query_even_when_environment_exports_a_root(
        self, tmp_path: Path
    ) -> None:
        """An exported PIPX_HOME cannot rescue a failed authoritative pipx query or alter its target."""
        fake_bin = FakeBin(root=tmp_path / "fixture")
        pipx_home: Path = tmp_path / "fixture" / "pipx-home"
        venv_root, _python_bin, user_launcher, _entry_launcher = fake_bin.make_launcher_layout(
            pipx_home=pipx_home
        )
        location: Path = venv_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location, pipx_home=pipx_home)
        pipx_path: Path = fake_bin._bin / "pipx"  # noqa: SLF001 - isolated fake command replacement.
        pipx_path.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "environment" ]; then exit 1; fi\n'
            'if [ "$1" = "runpip" ]; then echo "Location: ' + str(location) + '"; exit 0; fi\n'
            "exit 1\n"
        )
        pipx_path.chmod(0o755)
        before: bytes = user_launcher.read_bytes()

        result = fake_bin.run(
            snippet="slo_finalize_isolated_launcher",
            env={"PIPX_HOME": str(pipx_home)},
        )

        assert result.returncode != 0
        assert "PIPX_HOME' failed" in result.stderr
        assert user_launcher.read_bytes() == before

    def test_rejects_outer_slo_venv_symlink_even_when_it_points_inside_pipx_home(
        self, tmp_path: Path
    ) -> None:
        """The explicit ``PIPX_HOME/venvs/slo`` candidate is never a link write target."""
        fake_bin = FakeBin(root=tmp_path / "fixture")
        pipx_home: Path = tmp_path / "fixture" / "pipx-home"
        venv_root, _python_bin, user_launcher, _entry_launcher = fake_bin.make_launcher_layout(
            pipx_home=pipx_home
        )
        physical_root: Path = pipx_home / "venvs" / "slo-physical"
        physical_root.parent.mkdir(parents=True, exist_ok=True)
        venv_root.rename(physical_root)
        (pipx_home / "venvs" / "slo").symlink_to(physical_root.name)
        location: Path = physical_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location, pipx_home=pipx_home)

        result = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode != 0
        assert user_launcher.read_text().startswith("#!")
        assert "venv directory is a symlink" in result.stderr

    def test_rejects_symlinked_bin_directory_and_preserves_external_launchers(self, tmp_path: Path) -> None:
        """A venv ``bin`` link cannot redirect finalizer writes outside the direct child."""
        fake_bin = FakeBin(root=tmp_path / "fixture")
        pipx_home: Path = tmp_path / "fixture" / "pipx-home"
        venv_root, _python_bin, _user_launcher, _entry_launcher = fake_bin.make_launcher_layout(
            pipx_home=pipx_home
        )
        external_bin: Path = tmp_path / "fixture" / "external-bin"
        venv_root.joinpath("bin").rename(external_bin)
        venv_root.joinpath("bin").symlink_to(external_bin)
        external_user_launcher: Path = external_bin / "slo"
        before: bytes = external_user_launcher.read_bytes()
        location: Path = venv_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location, pipx_home=pipx_home)

        result = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode != 0
        assert "venv/bin directory is a symlink" in result.stderr
        assert external_user_launcher.read_bytes() == before

    def test_rejects_location_outside_validated_venv(self, tmp_path: Path) -> None:
        """Metadata that points outside pipx's Slo venv cannot authorize a write."""
        fixture_root: Path = tmp_path / "fixture"
        fake_bin = FakeBin(root=fixture_root)
        pipx_home: Path = fixture_root / "pipx-home"
        fake_bin.make_launcher_layout(pipx_home=pipx_home)
        outside: Path = fixture_root / "outside"
        outside.mkdir()
        fake_bin.write_fake_pipx(location=outside, pipx_home=pipx_home)

        result = fake_bin.run(snippet="slo_resolve_isolated_launcher_layout")

        assert result.returncode != 0
        assert "outside the validated slo venv" in result.stderr

    def test_rejects_missing_entry_launcher_without_writing_user_launcher(self, tmp_path: Path) -> None:
        """The resolver refuses incomplete generated artifacts before mutation."""
        fake_bin = FakeBin(root=tmp_path)
        pipx_home: Path = tmp_path / "pipx-home"
        venv_root, _python_bin, user_launcher, entry_launcher = fake_bin.make_launcher_layout(
            pipx_home=pipx_home
        )
        before: bytes = user_launcher.read_bytes()
        entry_launcher.unlink()
        location: Path = venv_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location, pipx_home=pipx_home)

        result = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode != 0
        assert user_launcher.read_bytes() == before

    @pytest.mark.parametrize("target_kind", ["absolute", "relative"])
    def test_accepts_external_base_python_only_after_venv_path_proves_prefix(
        self, tmp_path: Path, target_kind: str
    ) -> None:
        """A normal venv Python link retains its venv path after proving ``sys.prefix``."""
        fake_bin = FakeBin(root=tmp_path / "fixture")
        pipx_home: Path = tmp_path / "fixture" / "pipx-home"
        venv_root, python_bin, user_launcher, entry_launcher = fake_bin.make_launcher_layout(
            pipx_home=pipx_home
        )
        external: Path = tmp_path / "fixture" / "external" / "base-python"
        external.parent.mkdir()
        external.write_text(f"#!/bin/sh\nprintf '%s\\n' '{venv_root}'\n")
        external.chmod(0o755)
        python_bin.unlink()
        python_bin.symlink_to(external if target_kind == "absolute" else "../../../../external/base-python")
        location: Path = venv_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location, pipx_home=pipx_home)

        result = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode == 0, result.stderr
        assert f"python_bin={python_bin}" in self._resolve(fake_bin=fake_bin)
        assert f"exec '{python_bin}' -I '{entry_launcher}' \"$@\"" in user_launcher.read_text()

    def test_rejects_python_symlink_cycle(self, tmp_path: Path) -> None:
        """A cyclic venv-local chain fails closed rather than looping during finalization."""
        fake_bin = FakeBin(root=tmp_path)
        venv_root, python_bin, _user_launcher, _entry_launcher = fake_bin.make_launcher_layout()
        python_alt: Path = python_bin.with_name("python3.11")
        python_bin.unlink()
        python_alt.write_text("placeholder\n")
        python_alt.unlink()
        python_bin.symlink_to(python_alt.name)
        python_alt.symlink_to(python_bin.name)
        location: Path = venv_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location)

        result = fake_bin.run(snippet="slo_resolve_isolated_launcher_layout")

        assert result.returncode != 0
        assert "missing or unsafe" in result.stderr

    def test_accepts_a_multi_hop_python_symlink_chain_contained_by_the_venv(self, tmp_path: Path) -> None:
        """Realistic relative links are accepted only when every hop remains in the venv."""
        fake_bin = FakeBin(root=tmp_path)
        venv_root, python_bin, _user_launcher, _entry_launcher = fake_bin.make_launcher_layout()
        first_hop: Path = python_bin.with_name("python3")
        final_python: Path = python_bin.with_name("python3.11")
        python_bin.unlink()
        first_hop.symlink_to(final_python.name)
        final_python.write_text(f"#!/bin/sh\nprintf '%s\\n' '{venv_root}'\n")
        final_python.chmod(0o755)
        python_bin.symlink_to(first_hop.name)
        location: Path = venv_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location)

        output = self._resolve(fake_bin=fake_bin)

        assert f"python_bin={python_bin}" in output


class TestIsolatedLauncherWriter:
    """Exercise exact activation, idempotence, and conservative refusal paths."""

    def _prepare(self, *, tmp_path: Path) -> tuple[FakeBin, Path, Path, Path]:
        """Build a valid fake installation for one writer test.

        Args:
            tmp_path (Path): Test-local root.

        Returns:
            tuple[FakeBin, Path, Path, Path]: Harness, Python, user, and entry paths.
        """
        fake_bin = FakeBin(root=tmp_path)
        pipx_home: Path = tmp_path / "pipx-home"
        venv_root, python_bin, user_launcher, entry_launcher = fake_bin.make_launcher_layout(
            pipx_home=pipx_home
        )
        location: Path = venv_root / "site-packages"
        location.mkdir()
        fake_bin.write_fake_pipx(location=location, pipx_home=pipx_home)
        return fake_bin, python_bin, user_launcher, entry_launcher

    def test_finalizer_replaces_recognized_script_with_exact_wrapper_and_is_idempotent(
        self, tmp_path: Path
    ) -> None:
        """A fresh generated user launcher becomes the one canonical executable wrapper."""
        fake_bin, python_bin, user_launcher, entry_launcher = self._prepare(tmp_path=tmp_path)

        first = fake_bin.run(snippet="slo_finalize_isolated_launcher")
        first_bytes: bytes = user_launcher.read_bytes()
        second = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        expected: bytes = (
            b"#!/bin/sh\n"
            b"# >>> slo isolated launcher (v1) >>>\n"
            b"# Generated by the Slo installer; do not edit.\n"
            + f"exec '{python_bin}' -I '{entry_launcher}' \"$@\"\n".encode()
        )
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        assert first_bytes == expected
        assert user_launcher.read_bytes() == expected
        assert user_launcher.stat().st_mode & 0o777 == 0o755

    @pytest.mark.parametrize(
        "content", ["#!/bin/sh\n# >>> slo isolated launcher (v1) >>>\nchanged\n", "foreign\n"]
    )
    def test_finalizer_refuses_unknown_or_changed_launcher_and_preserves_bytes(
        self, tmp_path: Path, content: str
    ) -> None:
        """A marked difference or foreign file is never overwritten by a repair attempt."""
        fake_bin, _python_bin, user_launcher, _entry_launcher = self._prepare(tmp_path=tmp_path)
        user_launcher.write_text(content)
        before: bytes = user_launcher.read_bytes()

        result = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode != 0
        assert user_launcher.read_bytes() == before

    def test_finalizer_allows_pipx_managed_python_symlink(self, tmp_path: Path) -> None:
        """A standard pipx ``bin/python`` symlink is accepted after its target validates."""
        fake_bin, python_bin, user_launcher, entry_launcher = self._prepare(tmp_path=tmp_path)
        real_python: Path = python_bin.with_name("python3.11")
        python_bin.unlink()
        real_python.write_text(f"#!/bin/sh\nprintf '%s\\n' '{python_bin.parent.parent}'\n")
        real_python.chmod(0o755)
        python_bin.symlink_to(real_python.name)
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
        user_launcher.write_text(generated)
        entry_launcher.write_text(generated)

        result = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode == 0, result.stderr
        assert "slo isolated launcher" in user_launcher.read_text()

    def test_finalizer_preserves_original_when_staging_file_cannot_be_created(self, tmp_path: Path) -> None:
        """An atomic staging failure leaves the original generated launcher byte-identical."""
        fake_bin, _python_bin, user_launcher, _entry_launcher = self._prepare(tmp_path=tmp_path)
        before: bytes = user_launcher.read_bytes()
        fake_mktemp: Path = tmp_path / "bin" / "mktemp"
        fake_mktemp.write_text("#!/bin/sh\nexit 1\n")
        fake_mktemp.chmod(0o755)

        result = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode != 0
        assert user_launcher.read_bytes() == before
        assert not list(user_launcher.parent.glob(".slo.*"))

    def test_managed_environment_writer_refuses_when_mktemp_is_unavailable(self, tmp_path: Path) -> None:
        """A missing portable mktemp refuses rather than invoking an unvalidated fallback."""
        fake_bin = FakeBin(root=tmp_path)
        location: Path = fake_bin.make_package_location()
        fake_bin.write_fake_pipx(location=location)
        fake_mktemp: Path = tmp_path / "bin" / "mktemp"
        fake_mktemp.write_text("#!/bin/sh\nexit 1\n")
        fake_mktemp.chmod(0o755)

        skills_dir: Path = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "INDEX.md").write_text("# index\n")
        result = fake_bin.run(snippet=f"slo_write_managed_environment_file '{skills_dir}'")

        assert result.returncode != 0
        assert "failed to stage the managed environment file" in result.stderr
        assert "fallback" not in result.stderr.lower()

    def test_launcher_only_mode_does_not_call_pipx_install_or_touch_shell_profiles(
        self, tmp_path: Path
    ) -> None:
        """The dedicated mode only validates and writes the launcher boundary."""
        fake_bin, _python_bin, _user_launcher, _entry_launcher = self._prepare(tmp_path=tmp_path)
        result = fake_bin.run(snippet="main --finalize-launcher")

        assert result.returncode == 0, result.stderr
        assert not any(call.startswith("pipx install") for call in fake_bin.calls)
        assert all(not path.exists() for path in fake_bin.profile_paths.values())
