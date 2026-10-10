"""Contract tests for tagged installer publication and release ordering."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT: Path = REPOSITORY_ROOT.parent
MAKEFILE: Path = REPOSITORY_ROOT / "Makefile"
GITLAB_CI: Path = WORKSPACE_ROOT / ".gitlab-ci.yml"
MACOS_WORKFLOW: Path = REPOSITORY_ROOT / ".github" / "workflows" / "release-installer.yml"
RELEASE_EVIDENCE_DIRECTORY: Path = REPOSITORY_ROOT / "release-evidence"


def _dry_run_make(*, target: str, variables: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Render a Make target without executing external release commands.

    Args:
        target (str): Target to render.
        variables (dict[str, str]): Explicit Make variable assignments.

    Returns:
        subprocess.CompletedProcess[str]: Captured dry-run result.
    """
    command: list[str] = ["make", "-n", target, *[f"{key}={value}" for key, value in variables.items()]]
    return subprocess.run(command, cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)


class TestReleaseAutomation:
    """The existing Make targets own the release publication chain."""

    def test_release_only_creates_and_pushes_a_strict_semver_tag_for_the_gitlab_pipeline(self) -> None:
        """A release dry run accepts an immutable tag and leaves publication to GitLab."""
        result: subprocess.CompletedProcess[str] = _dry_run_make(
            target="release", variables={"VERSION": "v9.9.9-rc.1"}
        )

        assert result.returncode == 0, result.stderr
        output: str = result.stdout
        assert 'git push origin "v9.9.9-rc.1"' in output
        assert "publish-installer" not in output
        assert "release-installer-smoke" not in output
        assert "creating GitLab release" not in output
        assert "curl -fsS -X POST" not in output
        assert "GitLab tag pipeline" in output

    def test_release_rejects_invalid_version_before_any_git_command(self) -> None:
        """Invalid versions cannot reach checkout, pull, tag, or push commands."""
        invalid_versions: tuple[str, ...] = (
            "v01.2.3",
            "v1.2.3+build.7",
            "feature/launcher-repair",
            "a1b2c3d4",
        )

        for version in invalid_versions:
            result: subprocess.CompletedProcess[str] = _dry_run_make(
                target="release", variables={"VERSION": version}
            )

            assert result.returncode == 0, result.stderr
            commands: list[str] = [line for line in result.stdout.splitlines() if line]
            validation_index: int = next(
                index for index, command in enumerate(commands) if "strict SemVer tag" in command
            )
            git_indices: list[int] = [
                index
                for index, command in enumerate(commands)
                if command.startswith("git checkout")
                or command.startswith("git tag")
                or command.startswith("git push")
            ]
            assert git_indices
            assert validation_index < min(git_indices)

            executed: subprocess.CompletedProcess[str] = subprocess.run(
                ["make", "release", f"VERSION={version}"],
                cwd=REPOSITORY_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            assert executed.returncode != 0
            assert "strict SemVer tag" in executed.stderr
            assert "git" not in executed.stdout

    def test_publish_installer_preserves_explicit_tagged_refs(self) -> None:
        """Release composition forwards caller-selected matching source and publish refs to the deploy owner."""
        result: subprocess.CompletedProcess[str] = _dry_run_make(
            target="publish-installer",
            variables={
                "SLO_RELEASE_MODE": "1",
                "SLO_SOURCE_REF": "v9.9.9",
                "PUBLISH_SLO_REF": "v9.9.9",
                "SLO_SOURCE_PATH": "slo/install.sh",
            },
        )

        assert result.returncode == 0, result.stderr
        output: str = result.stdout
        assert "bash deploy-install-worker.sh" in output
        assert 'SLO_SOURCE_REF="${SLO_SOURCE_REF:-$(t=$(git tag' in output
        assert 'PUBLISH_SLO_REF="${PUBLISH_SLO_REF:-$(t=$(git tag' in output

    def test_gitlab_ci_parses_and_preserves_required_release_dependency_order(self) -> None:
        """The authoritative CI configuration is valid YAML with release-fatal dependencies."""
        pipeline: dict[str, object] = yaml.safe_load(GITLAB_CI.read_text())

        assert pipeline["stages"] == ["test", "publish", "release-verify", "release", "secret-detection"]
        publish_job: dict[str, object] = pipeline["publish-installer"]  # type: ignore[assignment]
        macos_job: dict[str, object] = pipeline["macos-installer-smoke"]  # type: ignore[assignment]
        release_job: dict[str, object] = pipeline["create-gitlab-release"]  # type: ignore[assignment]
        assert publish_job["needs"] == [{"job": "pytest"}]
        assert macos_job["needs"] == [{"job": "publish-installer"}]
        assert release_job["needs"] == [
            {"job": "release-pipx-recovery"},
            {"job": "release-docker-installer-matrix"},
            {"job": "hosted-installer-smoke"},
            {"job": "macos-installer-smoke"},
        ]

    def test_gitlab_macos_job_selects_python_311_before_poetry_install(self) -> None:
        """The macOS release runner verifies the project-supported interpreter before Poetry runs."""
        pipeline: dict[str, object] = yaml.safe_load(GITLAB_CI.read_text())
        macos_job: dict[str, object] = pipeline["macos-installer-smoke"]  # type: ignore[assignment]
        before_script: list[str] = macos_job["before_script"]  # type: ignore[assignment]

        assert before_script[:3] == [
            "command -v python3.11",
            "python3.11 -c 'import sys; assert sys.version_info[:2] == (3, 11)'",
            'python3.11 -m pip install "poetry==$POETRY_VERSION"',
        ]
        assert "python3.11 -m pip install --user pipx" in before_script
        assert "poetry env use python3.11" in before_script
        assert before_script.index("poetry env use python3.11") < before_script.index(
            "poetry install --no-interaction"
        )

    def test_gitlab_tag_publication_fetches_the_same_tagged_public_installer_source(self) -> None:
        """The real GitLab tag job forbids local installer bytes and pins all release source inputs."""
        content: str = GITLAB_CI.read_text()

        assert "publish-installer:" in content
        assert "- if: $CI_COMMIT_TAG" in content
        publish_job: str = content[content.index("publish-installer:") : content.index("secret_detection:")]
        assert "SLO_RELEASE_MODE=1" in publish_job
        assert 'SLO_SOURCE_REF="$CI_COMMIT_TAG"' in publish_job
        assert 'PUBLISH_SLO_REF="$CI_COMMIT_TAG"' in publish_job
        assert "SLO_SOURCE_PATH=slo/install.sh" in publish_job
        assert "INSTALL_SH=" not in publish_job
        assert "needs:" in publish_job
        assert "- job: pytest" in publish_job
        assert "format-and-lint" not in publish_job

    def test_gitlab_hosted_release_jobs_override_default_e2e_deselection_and_collect_the_smoke(
        self,
    ) -> None:
        """Hosted release jobs and local collection explicitly select the installer smoke."""
        pipeline: dict[str, object] = yaml.safe_load(GITLAB_CI.read_text())
        template_job: dict[str, object] = pipeline[".hosted-installer-smoke"]  # type: ignore[assignment]
        hosted_job: dict[str, object] = pipeline["hosted-installer-smoke"]  # type: ignore[assignment]
        macos_job: dict[str, object] = pipeline["macos-installer-smoke"]  # type: ignore[assignment]
        expected_command: str = (
            "poetry run pytest -o addopts='' tests/cli/test_hosted_installer_smoke.py -m e2e -v"
        )

        assert expected_command in template_job["script"]  # type: ignore[operator]
        assert hosted_job["extends"] == ".hosted-installer-smoke"
        assert macos_job["extends"] == ".hosted-installer-smoke"
        assert expected_command in macos_job["script"]  # type: ignore[operator]

        collection_environment: dict[str, str] = {
            **os.environ,
            "SLO_ENV": "test",
            "SLO_ROOT_DIR": str(REPOSITORY_ROOT),
            "SLO_APP_DIR": str(REPOSITORY_ROOT),
            "SLO_APP_NAME": "slo",
            "SLO_LOG_FORMAT": "text",
            "SLO_DEFAULT_MODEL_NAME": "gpt-5.4",
            "SLO_AUTO_VISUALIZE": "0",
            "SLO_ANTHROPIC_API_KEY": "ci-placeholder-tests-are-fully-mocked",
            "COLUMNS": "120",
            "LINES": "40",
        }
        # CI's Poetry command is asserted above. Collect with this test run's
        # interpreter so isolated locked environments need no Poetry executable.
        collection: subprocess.CompletedProcess[str] = subprocess.run(
            args=[
                sys.executable,
                "-m",
                "pytest",
                "-o",
                "addopts=",
                "tests/cli/test_hosted_installer_smoke.py",
                "-m",
                "e2e",
                "--collect-only",
                "-q",
            ],
            cwd=REPOSITORY_ROOT,
            env=collection_environment,
            capture_output=True,
            text=True,
            check=False,
        )

        assert collection.returncode == 0, collection.stderr
        assert "test_hosted_installer_installs_and_runs_the_tagged_product" in collection.stdout
        assert "2/6 tests collected (4 deselected)" in collection.stdout

    def test_gitlab_tag_pipeline_requires_local_wheel_recovery_and_docker_matrix_proofs(self) -> None:
        """Tag pipelines override default deselection for each required locally-built E2E proof."""
        pipeline: dict[str, object] = yaml.safe_load(GITLAB_CI.read_text())
        recovery_job: dict[str, object] = pipeline["release-pipx-recovery"]  # type: ignore[assignment]
        docker_job: dict[str, object] = pipeline["release-docker-installer-matrix"]  # type: ignore[assignment]

        assert recovery_job["extends"] == ".release-e2e"
        assert docker_job["extends"] == ".release-e2e"
        assert "variables" not in recovery_job
        # This job declares its image instead of relying on the template's
        # inheritance, so its apt bootstrap and Docker client contract remain
        # coupled when either job changes.
        assert docker_job["image"] == "python:3.11"
        docker_before_script: list[str] = docker_job["before_script"]  # type: ignore[assignment]
        assert (
            "apt-get update && apt-get install -y --no-install-recommends docker.io" in docker_before_script
        )
        assert all("apk" not in command for command in docker_before_script)
        assert "python3.11 -c 'import sys; assert sys.version_info[:2] == (3, 11)'" in docker_before_script
        assert "poetry env use python3.11" in docker_before_script
        template: dict[str, object] = pipeline[".release-e2e"]  # type: ignore[assignment]
        effective_image: str = str(docker_job.get("image", template["image"]))
        assert effective_image == "python:3.11"
        assert docker_job["parallel"] == {
            "matrix": [
                {"SLO_INSTALL_SMOKE_IMAGE": ["ubuntu:22.04", "ubuntu:24.04", "debian:12", "debian:13"]}
            ]
        }
        assert docker_job["services"] == [{"name": "docker:27-dind"}]
        docker_variables: dict[str, str] = docker_job["variables"]  # type: ignore[assignment]
        assert docker_variables["DOCKER_HOST"] == "tcp://docker:2375"
        assert docker_variables["DOCKER_TLS_CERTDIR"] == ""
        assert "docker info" in docker_job["before_script"]  # type: ignore[operator]
        assert "docker info" in docker_job["script"]  # type: ignore[operator]
        assert template["needs"] == [{"job": "publish-installer"}]
        assert template["variables"] == {
            "SLO_DIRECT_PIPX_RECOVERY_E2E": "1",
            "SLO_INSTALL_E2E": "1",
            "SLO_LOCAL_WHEEL": "$CI_PROJECT_DIR/slo/dist/slo-*.whl",
            "PIPX_BIN_DIR": "$CI_PROJECT_DIR/.tmp/slo-pipx-bin",
        }
        recovery_script: list[str] = template["script"]  # type: ignore[assignment]
        docker_script: list[str] = docker_job["script"]  # type: ignore[assignment]
        assert "poetry build --format wheel" in recovery_script
        assert "-o addopts=''" in recovery_script[-1]
        assert "test_direct_pipx_regeneration_recovers_through_packaged_finalizer" in recovery_script[-1]
        assert "tests/cli/test_install_smoke.py -m e2e -v" in docker_script[-1]
        assert "-o addopts=''" in docker_script[-1]
        assert "SLO_INSTALL_E2E" in template["variables"]  # type: ignore[operator]
        assert docker_job["parallel"] == {
            "matrix": [
                {"SLO_INSTALL_SMOKE_IMAGE": ["ubuntu:22.04", "ubuntu:24.04", "debian:12", "debian:13"]}
            ]
        }

    def test_docker_smoke_contract_consumes_the_assigned_image_and_workspace_path(self) -> None:
        """The GitLab matrix image is validated by the smoke test and invokes the mounted workspace script."""
        smoke_test: str = (REPOSITORY_ROOT / "tests" / "cli" / "test_install_smoke.py").read_text()

        assert 'os.environ.get("SLO_INSTALL_SMOKE_IMAGE", "")' in smoke_test
        assert "if assigned_image not in IMAGES:" in smoke_test
        assert "return [assigned_image]" in smoke_test
        assert '"bash /src/slo/tests/cli/install_smoke_container.sh"' in smoke_test
        assert "SLO_INSTALL_E2E=1 requires a usable docker executable on PATH" in smoke_test
        assert 'os.environ.get("SLO_INSTALL_E2E") != "1"' in smoke_test

    def test_gitlab_tag_pipeline_makes_hosted_and_macos_release_evidence_fatal(self) -> None:
        """The actual GitLab provider publishes, then waits for its release verification jobs."""
        content: str = GITLAB_CI.read_text()
        publish_start: int = content.index("publish-installer:")
        hosted_start: int = content.index("hosted-installer-smoke:")
        macos_start: int = content.index("macos-installer-smoke:")
        secret_start: int = content.index("secret_detection:")
        publish_job: str = content[publish_start:hosted_start]
        hosted_job: str = content[hosted_start:macos_start]
        macos_job: str = content[macos_start:secret_start]

        assert "release-verify" in content
        assert "needs:" in hosted_job
        assert "publish-installer" in hosted_job
        assert "needs:" in macos_job
        assert "publish-installer" in macos_job
        assert 'SLO_RELEASE_TAG: "$CI_COMMIT_TAG"' in hosted_job
        assert 'SLO_RELEASE_TAG: "$CI_COMMIT_TAG"' in macos_job
        assert 'SLO_INSTALL_URL: "https://get-slo.sh/install.sh"' in hosted_job
        assert 'SLO_INSTALL_URL: "https://get-slo.sh/install.sh"' in macos_job
        assert "tests/cli/test_hosted_installer_smoke.py -m e2e -v" in hosted_job
        assert "tests/cli/test_hosted_installer_smoke.py -m e2e -v" in macos_job
        assert "tags:" in macos_job
        assert "macos" in macos_job
        assert "command -v python3.11" in macos_job
        assert "python3.11 -c 'import sys; assert sys.version_info[:2] == (3, 11)'" in macos_job
        assert 'python3.11 -m pip install "poetry==$POETRY_VERSION"' in macos_job
        assert "python3.11 -m pip install --user pipx" in macos_job
        assert "poetry install --no-interaction" in macos_job
        assert (
            "poetry run pytest -o addopts='' tests/cli/test_hosted_installer_smoke.py -m e2e -v" in macos_job
        )
        assert "poetry3" not in macos_job
        assert "SLO_PLATFORM_SMOKE: macos" in macos_job
        assert "python3.11 -c 'import site; print(site.USER_BASE)'" in macos_job
        assert "command -v pipx" in macos_job
        assert "pipx --version" in macos_job
        assert "python3 -m site --user-base" not in macos_job

    def test_gitlab_tag_pipeline_creates_the_release_only_after_all_required_evidence(self) -> None:
        """GitLab alone creates a release after hosted Linux and macOS evidence passes."""
        content: str = GITLAB_CI.read_text()

        assert "create-gitlab-release:" in content
        release_start: int = content.index("create-gitlab-release:")
        release_job: str = content[release_start : content.index("secret_detection:")]
        assert "stage: release" in release_job
        assert "release-pipx-recovery" in release_job
        assert "release-docker-installer-matrix" in release_job
        assert "hosted-installer-smoke" in release_job
        assert "macos-installer-smoke" in release_job
        assert "CI_COMMIT_TAG" in release_job
        assert "curl -fsS -X POST" in release_job

    def test_gitlab_tag_pipeline_runs_non_e2e_tests_before_publication(self) -> None:
        """The release pipeline makes behavioral tests, not local lint, the publication prerequisite."""
        content: str = GITLAB_CI.read_text()
        pytest_start: int = content.index("pytest:")
        publish_start: int = content.index("publish-installer:")
        pytest_job: str = content[pytest_start:publish_start]
        publish_job: str = content[publish_start : content.index("secret_detection:")]

        assert "- if: $CI_COMMIT_TAG" in pytest_job
        assert "format-and-lint:" not in content
        assert "poetry run black --check" not in content
        assert "make lint" not in content
        assert "- job: pytest" in publish_job

    def test_repo_local_release_evidence_template_is_explicitly_non_evidence(self) -> None:
        """A read-only canonical spec target has a local template and exact operator destination."""
        readme: str = (RELEASE_EVIDENCE_DIRECTORY / "README.md").read_text()
        template: str = (RELEASE_EVIDENCE_DIRECTORY / "template.md").read_text()

        assert "canonical specifications directory" in readme
        assert "readlink -f specifications" in readme
        assert "not release results" in readme
        assert "TEMPLATE: not evidence" in template
        for heading in ("Identity", "Build and local pipx recovery", "Required CI release gates"):
            assert heading in template
        for required_field in (
            "Wheel SHA-256",
            "Linux non-E2E matrix",
            "macOS hosted installer",
            "Hosted installer URL/hash",
        ):
            assert required_field in template
        assert "Redacted failures" in template

    def test_github_workflow_is_not_release_authority(self) -> None:
        """An optional GitHub workflow has no independent release trigger or authority claim."""
        content: str = MACOS_WORKFLOW.read_text()

        assert "workflow_dispatch:" in content
        assert "push:" not in content
        assert "release authority" not in content.lower()

    def test_make_test_env_reports_clean_checkout_fallback_when_tests_env_is_absent(self) -> None:
        """The documented test target remains usable without the ignored environment file."""
        result: subprocess.CompletedProcess[str] = _dry_run_make(target="test-env", variables={})

        assert result.returncode == 0, result.stderr
        assert "fallback" in result.stdout

    def test_release_installer_smoke_requires_a_version(self) -> None:
        """The hosted smoke target fails before invoking pytest without a release tag."""
        result: subprocess.CompletedProcess[str] = _dry_run_make(
            target="release-installer-smoke", variables={}
        )

        assert result.returncode == 0, result.stderr
        assert 'test -n ""' in result.stdout
        assert "SLO_HOSTED_INSTALL_E2E=1" in result.stdout
