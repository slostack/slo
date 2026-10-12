"""Deterministic GitLab-outage contracts; no actual git or pipx processes run."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from src.cli.update import ShellEnvironmentDefaults, Updater


@pytest.fixture(autouse=True)
def clean_repository_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent host source overrides from affecting mirror contract tests."""
    monkeypatch.delenv(name="SLO_REPO_URL", raising=False)
    monkeypatch.delenv(name="SLO_REPO_FALLBACK_URL", raising=False)


class TestMirrorUpdate:
    """Update retries have one source switch and preserve every ref selector."""

    @pytest.mark.parametrize("ref", ["main", "v1.2.3", "abc123"])
    def test_outage_retries_same_ref_and_finalizes_once(self, ref: str) -> None:
        """An inaccessible primary retries the mirror before any finalization."""
        failure = subprocess.CalledProcessError(returncode=128, cmd=["pipx"])
        order: list[str] = []
        with (
            patch.object(Updater, "_pipx_install", side_effect=[failure, None]) as install,
            patch.object(Updater, "_remote_available", return_value=False),
            patch.object(
                ShellEnvironmentDefaults, "finalize_launcher", side_effect=lambda: order.append("launcher")
            ),
            patch.object(
                ShellEnvironmentDefaults, "ensure", side_effect=lambda **kwargs: order.append("environment")
            ),
        ):
            Updater.invoke(ref=ref)
        assert [call.kwargs["spec"] for call in install.call_args_list] == [
            f"git+{Updater.REPO_URL}@{ref}#subdirectory=slo",
            f"git+{Updater.FALLBACK_REPO_URL}@{ref}#subdirectory=slo",
        ]
        assert order == ["launcher", "environment"]

    def test_build_failure_does_not_retry(self) -> None:
        """A reachable primary means pipx's error is not an outage."""
        failure = subprocess.CalledProcessError(returncode=1, cmd=["pipx"])
        with (
            patch.object(Updater, "_pipx_install", side_effect=failure) as install,
            patch.object(Updater, "_remote_available", return_value=True),
            patch.object(ShellEnvironmentDefaults, "finalize_launcher") as finalize,
        ):
            with pytest.raises(subprocess.CalledProcessError):
                Updater.invoke(ref="main")
        install.assert_called_once()
        finalize.assert_not_called()

    def test_both_installs_fail_without_finalization(self) -> None:
        """Mirror errors propagate without touching shell state or looping."""
        failure = subprocess.CalledProcessError(returncode=1, cmd=["pipx"])
        with (
            patch.object(Updater, "_pipx_install", side_effect=failure) as install,
            patch.object(Updater, "_remote_available", return_value=False),
            patch.object(ShellEnvironmentDefaults, "finalize_launcher") as finalize,
            patch.object(ShellEnvironmentDefaults, "ensure") as ensure,
        ):
            with pytest.raises(subprocess.CalledProcessError):
                Updater.invoke(ref="main")
        assert install.call_count == 2
        finalize.assert_not_called()
        ensure.assert_not_called()

    @pytest.mark.parametrize("fallback", ["", Updater.REPO_URL])
    def test_disabled_or_duplicate_fallback_does_not_probe(
        self, fallback: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Disabled fallback propagates the original install failure immediately."""
        monkeypatch.setenv(name="SLO_REPO_FALLBACK_URL", value=fallback)
        with (
            patch.object(
                Updater,
                "_pipx_install",
                side_effect=subprocess.CalledProcessError(returncode=1, cmd=["pipx"]),
            ) as install,
            patch.object(Updater, "_remote_available") as probe,
        ):
            with pytest.raises(subprocess.CalledProcessError):
                Updater.invoke(ref="main")
        install.assert_called_once()
        probe.assert_not_called()

    def test_custom_primary_does_not_fall_back_to_slo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A fork install must never silently switch repositories."""
        monkeypatch.setenv(name="SLO_REPO_URL", value="https://example.org/fork.git")
        assert Updater._fallback_repo_url() == ""
        assert Updater._pipx_spec(ref="main").startswith("git+https://example.org/fork.git@")
        monkeypatch.setenv(name="SLO_REPO_FALLBACK_URL", value="https://example.net/fork.git")
        assert Updater._fallback_repo_url() == "https://example.net/fork.git"

    def test_missing_pipx_does_not_retry(self) -> None:
        """Missing local executables are not repository failures."""
        with (
            patch.object(Updater, "_pipx_install", side_effect=FileNotFoundError) as install,
            patch.object(Updater, "_remote_available") as probe,
        ):
            with pytest.raises(FileNotFoundError):
                Updater.invoke(ref="main")
        install.assert_called_once()
        probe.assert_not_called()


class TestMirrorReleaseLookup:
    """Release selection falls back only on transport failure, not absent tags."""

    @pytest.mark.parametrize(
        "failure",
        [
            subprocess.CalledProcessError(returncode=128, cmd=["git"]),
            subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        ],
    )
    def test_outage_resolves_numeric_latest_on_mirror(self, failure: Exception) -> None:
        """Mirror tags use the same numeric ordering and URL as normal lookup."""
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="a\trefs/tags/v1.9.0\nb\trefs/tags/v1.10.0\n"
        )
        with patch.object(Updater, "_ls_remote", side_effect=[failure, result]) as remote:
            assert Updater.resolve_latest_release_tag() == "v1.10.0"
        assert [call.kwargs["repo_url"] for call in remote.call_args_list] == [
            Updater.REPO_URL,
            Updater.FALLBACK_REPO_URL,
        ]

    def test_no_tags_on_reachable_primary_does_not_switch_sources(self) -> None:
        """No releases is a semantic error rather than an outage."""
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with patch.object(Updater, "_ls_remote", return_value=result) as remote:
            with pytest.raises(SystemExit, match="no vX.Y.Z"):
                Updater.resolve_latest_release_tag()
        remote.assert_called_once()

    def test_both_remotes_fail(self) -> None:
        """A mirror outage surfaces its transport error after one retry."""
        with patch.object(
            Updater, "_ls_remote", side_effect=subprocess.CalledProcessError(returncode=128, cmd=["git"])
        ) as remote:
            with pytest.raises(subprocess.CalledProcessError):
                Updater.resolve_latest_release_tag()
        assert remote.call_count == 2

    def test_disabled_fallback_stops_tag_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit opt-out applies to discovery as well as installation."""
        monkeypatch.setenv(name="SLO_REPO_FALLBACK_URL", value="")
        with patch.object(
            Updater, "_ls_remote", side_effect=subprocess.CalledProcessError(returncode=128, cmd=["git"])
        ) as remote:
            with pytest.raises(subprocess.CalledProcessError):
                Updater.resolve_latest_release_tag()
        remote.assert_called_once()

    @pytest.mark.parametrize(
        "failure",
        [
            subprocess.CalledProcessError(returncode=128, cmd=["git"]),
            subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        ],
    )
    def test_probe_failure_is_unavailable(self, failure: Exception) -> None:
        """Both nonzero git and timeout report an unavailable primary."""
        with patch.object(Updater, "_ls_remote", side_effect=failure):
            assert Updater._remote_available(repo_url=Updater.REPO_URL) is False

    def test_probe_has_timeout_and_does_not_embed_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Git authentication is external; sensitive setup tokens never enter argv."""
        monkeypatch.setenv(name="GITHUB_SLOSTACK_TOKEN", value="test-secret")
        with patch("src.cli.update.subprocess.run") as run:
            Updater._ls_remote(repo_url=Updater.FALLBACK_REPO_URL)
        assert "test-secret" not in str(run.call_args.kwargs["args"])
        assert run.call_args.kwargs["timeout"] == 30
        assert run.call_args.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
