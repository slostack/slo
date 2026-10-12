"""Real Bash mirror retries against disposable fake pipx/git executables."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from tests.cli.test_install import FakeBin, fake_bin  # noqa: F401 - shared isolated fixture.
from src.cli.update import Updater


def configure_commands(*, fake_bin: FakeBin, git_status: int = 128, mirror_status: int = 0) -> None:
    """Create deterministic outage commands under the fixture's isolated PATH.

    Args:
        fake_bin: Temp-owned executable and runtime fixture.
        git_status: Exit status for primary accessibility checks.
        mirror_status: Exit status for installing from GitHub.
    """
    fake_bin.write_regular_executable(
        path=fake_bin._bin / "pipx",
        content=(
            '#!/bin/sh\necho "pipx $*" >> "$SLO_CALL_LOG"\n'
            'case "$*" in\n'
            f"  *github.com*) exit {mirror_status} ;;\n"
            "  *) exit 17 ;;\nesac\n"
        ),
    )
    fake_bin.write_regular_executable(
        path=fake_bin._bin / "git",
        content=f'#!/bin/sh\necho "git $*" >> "$SLO_CALL_LOG"\nexit {git_status}\n',
    )
    fake_bin.write_regular_executable(
        path=fake_bin._bin / "python3.11",
        content=f'#!/bin/sh\nexec "{sys.executable}" "$@"\n',
    )


class TestInstallerMirror:
    """Installation source retries preserve version selection and failure cutoffs."""

    @pytest.mark.parametrize(
        "env,ref",
        [
            ({}, "main"),
            ({"SLO_REF": "v1.2.3"}, "v1.2.3"),
            ({"SLO_VERSION": "dev"}, "main"),
            ({"SLO_REF": "abc123"}, "abc123"),
        ],
    )
    def test_outage_retries_same_ref(self, fake_bin: FakeBin, env: dict[str, str], ref: str) -> None:
        """Source switches leave the Python interpreter, ref and subdir intact."""
        configure_commands(fake_bin=fake_bin)
        result = fake_bin.run(snippet="slo_install", env=env)
        assert result.returncode == 0, result.stderr
        installs = [call for call in fake_bin.calls if call.startswith("pipx install")]
        assert len(installs) == 2
        assert f"git+{Updater.REPO_URL}@{ref}#subdirectory=slo" in installs[0]
        assert f"git+{Updater.FALLBACK_REPO_URL}@{ref}#subdirectory=slo" in installs[1]
        assert "trying the mirror" in result.stderr

    def test_reachable_primary_preserves_build_error(self, fake_bin: FakeBin) -> None:
        """Dependency failures on a reachable source are not retried."""
        configure_commands(fake_bin=fake_bin, git_status=0)
        result = fake_bin.run(snippet="slo_install")
        assert result.returncode == 17
        assert not any("github.com" in call for call in fake_bin.calls)

    def test_both_sources_fail_without_shell_finalization(self, fake_bin: FakeBin) -> None:
        """The second failure returns nonzero and prevents subsequent steps."""
        configure_commands(fake_bin=fake_bin, mirror_status=19)
        result = fake_bin.run(snippet="slo_install\necho finalized")
        assert result.returncode == 19
        assert "finalized" not in result.stdout
        assert len([call for call in fake_bin.calls if call.startswith("pipx install")]) == 2

    @pytest.mark.parametrize(
        "env",
        [
            {"SLO_REPO_FALLBACK_URL": ""},
            {"SLO_REPO_FALLBACK_URL": Updater.REPO_URL},
            {"SLO_REPO_URL": "https://example.org/fork.git"},
        ],
    )
    def test_opt_out_duplicate_and_custom_repo_do_not_retry(
        self, fake_bin: FakeBin, env: dict[str, str]
    ) -> None:
        """Forks and explicit opt-outs do not get the official mirror."""
        configure_commands(fake_bin=fake_bin)
        result = fake_bin.run(snippet="slo_install", env=env)
        assert result.returncode == 17
        assert len(fake_bin.calls) == 1

    def test_custom_mirror_and_empty_subdir(self, fake_bin: FakeBin) -> None:
        """Both mirror and package location are configurable without changing refs."""
        configure_commands(fake_bin=fake_bin)
        result = fake_bin.run(
            snippet="slo_install",
            env={"SLO_REPO_FALLBACK_URL": "https://github.com/example/fork.git", "SLO_REPO_SUBDIR": ""},
        )
        assert result.returncode == 0
        assert "git+https://github.com/example/fork.git@main" in fake_bin.calls[-1]
        assert not any("#subdirectory=" in call for call in fake_bin.calls)

    def test_success_never_probes(self, fake_bin: FakeBin) -> None:
        """Healthy installs do not need an additional network call."""
        fake_bin.add(name="pipx")
        result = fake_bin.run(snippet="slo_install")
        assert result.returncode == 0
        assert len(fake_bin.calls) == 1

    def test_default_mirror_matches_updater(self, fake_bin: FakeBin) -> None:
        """Python and Bash use the same official destination."""
        result = fake_bin.run(snippet='echo "$SLO_REPO_FALLBACK_URL"')
        assert result.stdout.strip() == Updater.FALLBACK_REPO_URL

    def test_probe_timeout_is_unavailable(self, fake_bin: FakeBin) -> None:
        """The embedded portable probe terminates transport hangs after 30 seconds."""
        from tests.cli.test_install import INSTALL_SH

        source = INSTALL_SH.read_text()
        code = source.split("slo_remote_available() {", 1)[1].split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        with (
            patch.object(sys, "argv", ["probe", Updater.REPO_URL]),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30)) as run,
        ):
            with pytest.raises(SystemExit) as exit_info:
                exec(code, {})
        assert exit_info.value.code == 1
        assert run.call_args.kwargs["timeout"] == 30

    def test_missing_local_git_is_not_outage(self, fake_bin: FakeBin) -> None:
        """The portable probe does not retry for a broken local toolchain."""
        configure_commands(fake_bin=fake_bin)
        (fake_bin._bin / "git").unlink()
        result = fake_bin.run(snippet="slo_install")
        assert result.returncode == 17
        assert len(fake_bin.calls) == 1
