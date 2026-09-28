"""Subprocess contracts for the installer Worker deployment helper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT: Path = REPOSITORY_ROOT / "deploy-install-worker.sh"


def _write_stub_tools(*, root: Path, curl_exit_code: int = 0) -> Path:
    """Create deterministic command stubs for deployment-script validation paths.

    Args:
        root (Path): Temporary test root.
        curl_exit_code (int): Exit code for the curl stub when it is reached.

    Returns:
        Path: Directory prepended to PATH.
    """
    bin_dir: Path = root / "bin"
    bin_dir.mkdir()
    curl: Path = bin_dir / "curl"
    curl.write_text(f"#!/bin/sh\nexit {curl_exit_code}\n")
    curl.chmod(0o755)
    return bin_dir


def _run_deploy(
    *, tmp_path: Path, extra_environment: dict[str, str], curl_exit_code: int = 0
) -> subprocess.CompletedProcess[str]:
    """Run the deployment helper in a no-network, disposable environment.

    Args:
        tmp_path (Path): Temporary filesystem root.
        extra_environment (dict[str, str]): Contract-specific environment values.
        curl_exit_code (int): Stub curl failure code when validation permits a request.

    Returns:
        subprocess.CompletedProcess[str]: Captured script result.
    """
    bin_dir: Path = _write_stub_tools(root=tmp_path, curl_exit_code=curl_exit_code)
    environment: dict[str, str] = dict(os.environ)
    environment.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{environment['PATH']}",
            "CLOUDFLARE_API_TOKEN": "test-token",
            "CLOUDFLARE_ACCOUNT_ID": "test-account",
        }
    )
    environment.update(extra_environment)
    return subprocess.run(
        ["bash", str(DEPLOY_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


class TestDeployInstallWorker:
    """Release-mode validation precedes all network publication behavior."""

    @pytest.mark.parametrize(
        ("environment", "message"),
        [
            (
                {"SLO_RELEASE_MODE": "1", "SLO_SOURCE_REF": "main", "PUBLISH_SLO_REF": "main"},
                "requires an immutable vMAJOR.MINOR.PATCH SLO_SOURCE_REF tag",
            ),
            *[
                (
                    {"SLO_RELEASE_MODE": "1", "SLO_SOURCE_REF": tag, "PUBLISH_SLO_REF": tag},
                    "requires an immutable vMAJOR.MINOR.PATCH SLO_SOURCE_REF tag",
                )
                for tag in ("v1x.2.3", "v1.2x.3", "v1.2.3x", "v1.2", "v1.2.3-", "feature/x", "a1b2c3d")
            ],
            (
                {
                    "SLO_RELEASE_MODE": "1",
                    "SLO_SOURCE_REF": "feature/launcher-repair",
                    "PUBLISH_SLO_REF": "feature/launcher-repair",
                },
                "requires an immutable vMAJOR.MINOR.PATCH SLO_SOURCE_REF tag",
            ),
            (
                {"SLO_RELEASE_MODE": "1", "SLO_SOURCE_REF": "v1.2.3", "PUBLISH_SLO_REF": "v1.2.4"},
                "requires SLO_SOURCE_REF and PUBLISH_SLO_REF to match",
            ),
            (
                {
                    "SLO_RELEASE_MODE": "1",
                    "SLO_SOURCE_REF": "v1.2.3",
                    "PUBLISH_SLO_REF": "v1.2.3",
                    "SLO_SOURCE_PATH": "install.sh",
                },
                "requires SLO_SOURCE_PATH=slo/install.sh",
            ),
            (
                {
                    "SLO_RELEASE_MODE": "1",
                    "SLO_SOURCE_REF": "v1.2.3",
                    "PUBLISH_SLO_REF": "v1.2.3",
                    "SLO_SOURCE_PATH": "slo/install.sh",
                    "INSTALL_SH": "/tmp/local-install.sh",
                },
                "forbids the local INSTALL_SH override",
            ),
        ],
    )
    def test_release_mode_rejects_non_public_or_mismatched_inputs(
        self, tmp_path: Path, environment: dict[str, str], message: str
    ) -> None:
        """Invalid release inputs fail before the helper can call curl.

        Args:
            tmp_path (Path): Temporary executable root.
            environment (dict[str, str]): Release-mode input variant.
            message (str): Required diagnostic fragment.
        """
        result: subprocess.CompletedProcess[str] = _run_deploy(
            tmp_path=tmp_path, extra_environment=environment, curl_exit_code=99
        )

        assert result.returncode != 0
        assert message in result.stderr
        assert "HTTP call failed" not in result.stderr

    @pytest.mark.parametrize("tag", ["v1.2.3-rc.1", "v1.2.3-0", "v1.2.3-alpha-beta.9"])
    def test_release_mode_accepts_strict_semver_prerelease(self, tmp_path: Path, tag: str) -> None:
        """Intended SemVer prereleases pass syntax validation before any HTTP action."""
        result: subprocess.CompletedProcess[str] = _run_deploy(
            tmp_path=tmp_path,
            extra_environment={
                "SLO_RELEASE_MODE": "1",
                "SLO_SOURCE_REF": tag,
                "PUBLISH_SLO_REF": tag,
                "SLO_SOURCE_PATH": "slo/install.sh",
            },
            curl_exit_code=7,
        )

        assert result.returncode != 0
        assert "HTTP call failed" in result.stderr
        assert "requires an immutable" not in result.stderr

    def test_release_mode_constructs_tagged_public_source_url_before_publication(
        self, tmp_path: Path
    ) -> None:
        """A valid release reaches only the tagged public-source fetch after preflight validation."""
        result: subprocess.CompletedProcess[str] = _run_deploy(
            tmp_path=tmp_path,
            extra_environment={
                "SLO_RELEASE_MODE": "1",
                "SLO_SOURCE_REF": "v1.2.3",
                "PUBLISH_SLO_REF": "v1.2.3",
                "SLO_SOURCE_PATH": "slo/install.sh",
                "SLO_REPO_PROJECT": "public/example",
            },
            curl_exit_code=7,
        )

        assert result.returncode != 0
        assert "HTTP call failed" in result.stderr
        assert "requires" not in result.stderr

    def test_development_mode_remains_explicitly_non_release(self, tmp_path: Path) -> None:
        """Default development publication permits main and reaches its first external check."""
        result: subprocess.CompletedProcess[str] = _run_deploy(
            tmp_path=tmp_path,
            extra_environment={"SLO_SOURCE_REF": "main", "PUBLISH_SLO_REF": "main"},
            curl_exit_code=7,
        )

        assert result.returncode != 0
        assert "HTTP call failed" in result.stderr
        assert "release publication requires" not in result.stderr
