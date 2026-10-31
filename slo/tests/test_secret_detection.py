"""Secret detection must run, block on failure, and also guard commits locally."""

from pathlib import Path
from typing import Any

import yaml

PROJECT: Path = Path(__file__).resolve().parents[1]
REPOSITORY: Path = PROJECT.parent


def _pipeline() -> dict[str, Any]:
    """Load the GitLab pipeline definition from the repository root.

    Returns:
        dict[str, Any]: Parsed ``.gitlab-ci.yml``.
    """
    return yaml.safe_load((REPOSITORY / ".gitlab-ci.yml").read_text(encoding="utf-8"))


def test_secret_detection_failure_blocks_the_pipeline() -> None:
    """A scan that fails or never runs must turn the pipeline red, not pass silently."""
    assert _pipeline()["secret_detection"]["allow_failure"] is False


def test_secret_detection_retries_only_infrastructure_failures() -> None:
    """Runner faults are retried; a real finding (script failure) is never retried away."""
    retry: dict[str, Any] = _pipeline()["secret_detection"]["retry"]
    assert retry["max"] == 2
    assert set(retry["when"]) == {"runner_system_failure", "runner_configuration_error", "scheduler_failure"}


def test_commits_are_scanned_locally_by_pinned_gitleaks() -> None:
    """The pre-commit hook scans staged changes with a pinned gitleaks release."""
    config: dict[str, Any] = yaml.safe_load((REPOSITORY / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    (gitleaks,) = [repo for repo in config["repos"] if repo["repo"] == "https://github.com/gitleaks/gitleaks"]
    assert gitleaks["rev"] == "v8.29.1"
    assert [hook["id"] for hook in gitleaks["hooks"]] == ["gitleaks"]
