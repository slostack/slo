"""Safety and failure-preservation contracts for the installer-owned launcher writer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.cli.test_install import FakeBin


def _generated_launcher(*, python_bin: Path) -> str:
    """Return the exact supported pip-generated console script for ``src.cli:main``.

    Args:
        python_bin: Validated venv interpreter path used by the generated shebang.

    Returns:
        str: Exact unmarked generated launcher contract.
    """
    return (
        f"#!{python_bin}\n"
        "# -*- coding: utf-8 -*-\n"
        "import re\n"
        "import sys\n"
        "from src.cli import main\n\n"
        "if __name__ == '__main__':\n"
        "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
        "    sys.exit(main())\n"
    )


def _write_failure_tool(*, fake_bin: FakeBin, name: str, body: str) -> None:
    """Replace one fake shell tool with a deterministic failing implementation.

    Args:
        fake_bin: Isolated shell-tool harness.
        name: Tool name placed ahead of host PATH.
        body: Shell command body after the shebang.
    """
    path: Path = fake_bin._bin / name  # noqa: SLF001 - intentional shell harness injection.
    if path.is_symlink():
        path.unlink()
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def fake_bin(tmp_path: Path) -> FakeBin:
    """Build a focused installer writer harness.

    Args:
        tmp_path: Test-owned filesystem root.

    Returns:
        FakeBin: Isolated PATH and pipx metadata fixture.
    """
    return FakeBin(root=tmp_path)


class TestIsolatedLauncherWriter:
    """The writer refuses unsafe targets and preserves a prior launcher on every failure."""

    def _layout(self, fake_bin: FakeBin) -> tuple[Path, Path, Path, Path]:
        """Build a resolver-valid fixture layout and metadata.

        Args:
            fake_bin: Isolated shell-tool harness.

        Returns:
            tuple[Path, Path, Path, Path]: Venv, Python, user launcher, and entry launcher.
        """
        venv_root, python_bin, user_launcher, entry_launcher = fake_bin.make_launcher_layout()
        location: Path = venv_root / "lib" / "python3.11" / "site-packages"
        location.mkdir(parents=True)
        fake_bin.write_fake_pipx(location=location, pipx_home=venv_root.parents[1])
        return venv_root, python_bin, user_launcher, entry_launcher

    def _write(
        self, fake_bin: FakeBin, *, user_launcher: Path, python_bin: Path, entry_launcher: Path
    ) -> subprocess.CompletedProcess[str]:
        """Invoke the shell writer directly.

        Args:
            fake_bin: Isolated shell-tool harness.
            user_launcher: Existing generated user launcher.
            python_bin: Validated venv Python.
            entry_launcher: Validated generated trampoline.

        Returns:
            subprocess.CompletedProcess[str]: Writer result.
        """
        return fake_bin.run(
            snippet=(f'slo_write_isolated_launcher "{user_launcher}" "{python_bin}" "{entry_launcher}"')
        )

    def test_finalizer_replaces_both_exact_recognized_launchers(self, fake_bin: FakeBin) -> None:
        """Finalization verifies both scripts and writes the canonical non-recursive wrapper."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)

        result: subprocess.CompletedProcess[str] = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode == 0, result.stderr
        rendered: str = user_launcher.read_text()
        assert f"exec '{python_bin}' -I '{entry_launcher}' \"$@\"" in rendered
        assert "src.cli" not in rendered

    @pytest.mark.parametrize("artifact", ["user", "entry"])
    def test_finalizer_rejects_symlink_without_touching_external_target(
        self, fake_bin: FakeBin, artifact: str
    ) -> None:
        """Either launcher link is rejected before content reads or writes touch its external target."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)
        selected: Path = user_launcher if artifact == "user" else entry_launcher
        external_root: Path = fake_bin._root / "external-symlink-target"  # noqa: SLF001 - fixture boundary.
        external_root.mkdir()
        external: Path = external_root / f"outside-{artifact}"
        external.write_bytes(b"external bytes remain exact\n")
        selected.unlink()
        selected.symlink_to(external)

        result: subprocess.CompletedProcess[str] = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode != 0
        assert selected.is_symlink()
        assert external.read_bytes() == b"external bytes remain exact\n"

    @pytest.mark.parametrize("artifact", ["user", "entry"])
    def test_finalizer_rejects_directory_or_fifo_artifact(self, fake_bin: FakeBin, artifact: str) -> None:
        """Directories and special launcher artifacts fail closed before finalization."""
        _, _, user_launcher, entry_launcher = self._layout(fake_bin)
        selected: Path = user_launcher if artifact == "user" else entry_launcher
        selected.unlink()
        os.mkfifo(selected)

        result: subprocess.CompletedProcess[str] = fake_bin.run(snippet="slo_finalize_isolated_launcher")

        assert result.returncode != 0
        assert selected.exists()

    @pytest.mark.parametrize(
        "replacement",
        [
            b"#!/bin/sh\n# >>> slo isolated launcher (v1) >>>\nforeign\n",
            b"#!/bin/sh\n# >>> slo isolated launcher (v1) >>>\n# >>> slo isolated launcher (v1) >>>\n",
            b"#!/bin/sh\x00from src.cli import main\n",
            b"x" * 65537,
            b"#!/bin/sh\nfrom src.cli import main\nmain()\n",
        ],
    )
    def test_writer_refuses_ambiguous_or_foreign_user_content_byte_for_byte(
        self, fake_bin: FakeBin, replacement: bytes
    ) -> None:
        """Unrecognized, marked, NUL, and oversized files are not replacement candidates."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)
        user_launcher.write_bytes(replacement)

        result: subprocess.CompletedProcess[str] = self._write(
            fake_bin, user_launcher=user_launcher, python_bin=python_bin, entry_launcher=entry_launcher
        )

        assert result.returncode != 0
        assert user_launcher.read_bytes() == replacement

    @pytest.mark.parametrize(
        ("tool", "body"),
        [
            ("mktemp", "exit 1"),
            ("python3", "exit 1"),
            ("chmod", "exit 1"),
            ("mv", "exit 1"),
        ],
    )
    def test_writer_failure_preserves_existing_launcher_and_removes_stage(
        self, fake_bin: FakeBin, tool: str, body: str
    ) -> None:
        """Staging, chmod, and rename failures retain original bytes and leak no temporary file."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)
        original: bytes = _generated_launcher(python_bin=python_bin).encode()
        user_launcher.write_bytes(original)
        _write_failure_tool(fake_bin=fake_bin, name=tool, body=body)

        result: subprocess.CompletedProcess[str] = self._write(
            fake_bin, user_launcher=user_launcher, python_bin=python_bin, entry_launcher=entry_launcher
        )

        assert result.returncode != 0
        assert user_launcher.read_bytes() == original
        if tool != "mktemp":
            assert list(user_launcher.parent.glob(".slo.*")) == []

    def test_writer_rejects_preexisting_external_regular_file_returned_by_mktemp(
        self, fake_bin: FakeBin
    ) -> None:
        """A compromised mktemp cannot overwrite, chmod, fsync, or remove an external regular file."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)
        original: bytes = _generated_launcher(python_bin=python_bin).encode()
        user_launcher.write_bytes(original)
        external_root: Path = fake_bin._root / "external-staging-target"  # noqa: SLF001 - fixture boundary.
        external_root.mkdir()
        external: Path = external_root / "preexisting-regular-file"
        external.write_bytes(b"external bytes remain exact\n")
        external.chmod(0o640)
        external_mode: int = external.stat().st_mode & 0o777
        _write_failure_tool(
            fake_bin=fake_bin,
            name="mktemp",
            body=f'printf "%s\\n" "{external}"',
        )

        result: subprocess.CompletedProcess[str] = self._write(
            fake_bin, user_launcher=user_launcher, python_bin=python_bin, entry_launcher=entry_launcher
        )

        assert result.returncode != 0
        assert user_launcher.read_bytes() == original
        assert external.read_bytes() == b"external bytes remain exact\n"
        assert external.stat().st_mode & 0o777 == external_mode

    def test_writer_rejects_symlink_returned_by_mktemp_before_writing_external_target(
        self, fake_bin: FakeBin
    ) -> None:
        """A compromised staging result is rejected without touching its external link target."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)
        original: bytes = _generated_launcher(python_bin=python_bin).encode()
        user_launcher.write_bytes(original)
        external_root: Path = fake_bin._root / "external-staging-target"  # noqa: SLF001 - fixture boundary.
        external_root.mkdir()
        external: Path = external_root / "launcher"
        external.write_bytes(b"external bytes remain exact\n")
        staged: Path = user_launcher.parent / ".slo.symlink"
        _write_failure_tool(
            fake_bin=fake_bin,
            name="mktemp",
            body=f'ln -s "{external}" "{staged}" && printf "%s\\n" "{staged}"',
        )

        result: subprocess.CompletedProcess[str] = self._write(
            fake_bin, user_launcher=user_launcher, python_bin=python_bin, entry_launcher=entry_launcher
        )

        assert result.returncode != 0
        assert user_launcher.read_bytes() == original
        assert not staged.exists()
        assert external.read_bytes() == b"external bytes remain exact\n"

    def test_directory_fsync_failure_warns_after_atomic_rename_and_reports_success(
        self, fake_bin: FakeBin
    ) -> None:
        """Activation succeeds when post-rename directory durability is unavailable."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)

        result: subprocess.CompletedProcess[str] = fake_bin.run(
            snippet=(
                "slo_sync_directory() { return 1; }; "
                f'slo_write_isolated_launcher "{user_launcher}" "{python_bin}" "{entry_launcher}"'
            )
        )

        assert result.returncode == 0, result.stderr
        assert "warning: isolated launcher was activated" in result.stderr
        assert "slo isolated launcher" in user_launcher.read_text()

    def test_directory_fsync_runs_after_atomic_rename(self, fake_bin: FakeBin) -> None:
        """The durability helper is called only after the staged wrapper has been activated."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)

        result: subprocess.CompletedProcess[str] = fake_bin.run(
            snippet=(
                f'slo_sync_directory() {{ grep -q "slo isolated launcher" "{user_launcher}"; }}; '
                f'slo_write_isolated_launcher "{user_launcher}" "{python_bin}" "{entry_launcher}"'
            )
        )

        assert result.returncode == 0, result.stderr

    def test_writer_failure_when_write_is_unwritable_preserves_existing_launcher(
        self, fake_bin: FakeBin
    ) -> None:
        """A staging write failure preserves the generated target and removes the temporary file."""
        _, python_bin, user_launcher, entry_launcher = self._layout(fake_bin)
        original: bytes = _generated_launcher(python_bin=python_bin).encode()
        user_launcher.write_bytes(original)
        target_dir: Path = user_launcher.parent
        _write_failure_tool(fake_bin=fake_bin, name="mktemp", body=f'printf "%s\\n" "{target_dir}"')

        result: subprocess.CompletedProcess[str] = self._write(
            fake_bin, user_launcher=user_launcher, python_bin=python_bin, entry_launcher=entry_launcher
        )

        assert result.returncode != 0
        assert user_launcher.read_bytes() == original
        assert list(user_launcher.parent.glob(".slo.*")) == []
