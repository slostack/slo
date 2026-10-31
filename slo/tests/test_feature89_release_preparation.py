"""Offline guards for the bounded Feature 89 release candidate configuration."""

from pathlib import Path
import tomllib

import yaml  # type: ignore[import-untyped]

APP_ROOT = Path(__file__).resolve().parents[1]


def test_release_candidate_version_and_notes_agree() -> None:
    """Keep current metadata and release notes aligned without installing it."""
    project = tomllib.loads((APP_ROOT / "pyproject.toml").read_text())
    version = project["project"]["version"]
    notes = (APP_ROOT / "CHANGELOG.md").read_text()
    assert f"## [{version}] — " in notes
    for identity in ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol", "openrouter:typesafe/jev-router"):
        assert identity in notes
    assert "subscription OAuth" in notes
    assert "not live entitlement" in notes


def test_v0301_release_metadata_preserves_packaging_owned_launchers() -> None:
    """The corrected release version keeps both pipx-generated launcher contracts."""
    project: dict[str, object] = tomllib.loads((APP_ROOT / "pyproject.toml").read_text())["project"]
    assert project["version"] == "0.30.1"
    assert project["scripts"] == {"slo": "src.cli:main", "slo-entry": "src.cli:main"}
    assert "## [0.30.1] — " in (APP_ROOT / "CHANGELOG.md").read_text()


def test_runner_defaults_cover_inherited_jobs_and_preserve_macos() -> None:
    """Require both runner tags, including jobs supplied by GitLab's include."""
    pipeline = yaml.safe_load((APP_ROOT.parent / ".gitlab-ci.yml").read_text())
    required = {"mgr-01", "shared"}
    assert set(pipeline["default"]["tags"]) == required
    assert set(pipeline["macos-installer-smoke"]["tags"]) == required | {"macos"}
    assert pipeline["include"] == [{"template": "Security/Secret-Detection.gitlab-ci.yml"}]
    for name, job in pipeline.items():
        if not isinstance(job, dict) or name in {"default", "variables"}:
            continue
        if "trigger" in job:
            assert "tags" not in job, name
            continue
        if "tags" in job:
            assert required <= set(job["tags"]), name
        assert job.get("inherit", {}).get("default", True) is not False, name
