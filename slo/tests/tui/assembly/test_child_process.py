"""Focused tests for the public child-process assembly-selection boundary."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.tui.assembly import (
    SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO,
    DefaultSloTuiAssemblyChildProcessLauncher,
    DefaultSloTuiAssemblyChildProcessRunner,
    SloTuiAssemblyChildProcessRequestDAO,
    SloTuiAssemblyChildRunner,
    SloTuiAssemblyChildSelectionError,
)
from src.tui.assembly.child_process import main
from src.tui.assembly.dao import SloTuiAssemblyConfigDAO


class _RecordingAssemblyFactory:
    """Record child assembly delegation without constructing a session or application."""

    def __init__(self) -> None:
        """Create an empty configuration record."""
        self.configurations: list[SloTuiAssemblyConfigDAO] = []

    def run(self, *, config: SloTuiAssemblyConfigDAO) -> None:
        """Record validated child configuration without provider activity.

        Args:
            config (SloTuiAssemblyConfigDAO): Closed child assembly input.
        """
        self.configurations.append(config)


def _arguments(*, workdir: Path) -> tuple[str, ...]:
    """Build behavior-compatible child arguments from resolved CLI facts.

    Args:
        workdir (Path): Absolute directory forwarded to the child.

    Returns:
        tuple[str, ...]: Arguments accepted by the public child runner.
    """
    return ("--workdir", str(workdir))


class TestSloTuiAssemblyChildRunner:
    """Verify child-side selection fails closed before downstream assembly."""

    def test_run_accepts_only_the_allowlisted_selection(self, tmp_path: Path) -> None:
        """The valid explicit selection reaches the public assembly factory exactly once."""
        factory: _RecordingAssemblyFactory = _RecordingAssemblyFactory()
        runner: SloTuiAssemblyChildRunner = SloTuiAssemblyChildRunner(assembly_factory=factory)

        exit_code: int = runner.run(
            arguments=_arguments(workdir=tmp_path),
            environment={SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO: "textual_current"},
        )

        assert exit_code == 0
        assert factory.configurations == [
            SloTuiAssemblyConfigDAO(environment_scenario="textual_current", workdir=tmp_path)
        ]

    @pytest.mark.parametrize(
        "environment",
        [
            {},
            {SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO: "slotui"},
            {SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO: "textual_current\x00forged"},
            {SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO: 7},
        ],
    )
    def test_run_rejects_missing_malformed_or_unknown_selection_before_assembly(
        self,
        environment: dict[str, object],
        tmp_path: Path,
    ) -> None:
        """Invalid selection constructs neither an assembly factory nor provider-facing collaborators."""
        factory: _RecordingAssemblyFactory = _RecordingAssemblyFactory()
        runner: SloTuiAssemblyChildRunner = SloTuiAssemblyChildRunner(assembly_factory=factory)

        with pytest.raises(SloTuiAssemblyChildSelectionError):
            runner.run(arguments=_arguments(workdir=tmp_path), environment=environment)

        assert factory.configurations == []

    def test_default_child_cli_fails_closed_without_an_explicit_selection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A direct child invocation exits before assembly when its selection is absent."""
        monkeypatch.delenv(SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO, raising=False)

        exit_code: int = main(arguments=_arguments(workdir=tmp_path))

        assert exit_code == 2


class TestDefaultSloTuiAssemblyChildProcessLauncher:
    """Verify safe selection propagation and process reaping through public ports."""

    def test_build_request_rejects_a_forged_scenario_before_building_the_child_environment(
        self,
        tmp_path: Path,
    ) -> None:
        """A bypassed Pydantic literal check cannot propagate a non-selected child scenario."""
        forged_config: SloTuiAssemblyConfigDAO = SloTuiAssemblyConfigDAO(
            environment_scenario="textual_current",
            workdir=tmp_path,
        ).model_copy(update={"environment_scenario": "slotui"})

        with pytest.raises(SloTuiAssemblyChildSelectionError, match="unsupported"):
            DefaultSloTuiAssemblyChildProcessLauncher().build_request(config=forged_config)

    def test_build_request_propagates_only_validated_selection_in_sanitized_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The launcher overrides forged parent selection and preserves behavior-compatible child args."""
        monkeypatch.setenv(SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO, "slotui")
        monkeypatch.setenv("SLO_OPENAI_API_KEY", "secret")
        monkeypatch.setenv("UNRELATED_PARENT_VALUE", "drop-me")
        config: SloTuiAssemblyConfigDAO = SloTuiAssemblyConfigDAO(
            environment_scenario="textual_current",
            workdir=tmp_path,
            workspace_file=tmp_path / "workspace.code-workspace",
            resume_session_id="session-1",
            plugin_paths=(tmp_path / "plugin-one.py", tmp_path / "plugin-two.py"),
        )

        request: SloTuiAssemblyChildProcessRequestDAO = (
            DefaultSloTuiAssemblyChildProcessLauncher().build_request(config=config)
        )

        assert request.environment[SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO] == "textual_current"
        assert "SLO_OPENAI_API_KEY" not in request.environment
        assert "UNRELATED_PARENT_VALUE" not in request.environment
        assert Path(request.environment["PYTHONPATH"].split(":")[0]) == Path(__file__).parents[3]
        assert "sitecustomize" not in request.environment["PYTHONPATH"]
        assert request.argv == (
            sys.executable,
            "-m",
            "src.tui.assembly.child_process",
            "--workdir",
            str(tmp_path),
            "--workspace-file",
            str(tmp_path / "workspace.code-workspace"),
            "--resume-session-id",
            "session-1",
            "--plugin-path",
            str(tmp_path / "plugin-one.py"),
            "--plugin-path",
            str(tmp_path / "plugin-two.py"),
        )

    def test_runner_returns_child_exit_code_after_reaping_the_process(self, tmp_path: Path) -> None:
        """The public process runner waits for a launched child and reports its real terminal code."""
        request: SloTuiAssemblyChildProcessRequestDAO = SloTuiAssemblyChildProcessRequestDAO(
            argv=(sys.executable, "-c", "raise SystemExit(7)"),
            environment={"PATH": "/usr/bin"},
            cwd=tmp_path,
        )

        result = DefaultSloTuiAssemblyChildProcessRunner().run(request=request)

        assert result.exit_code == 7
        assert result.reaped is True

    def test_child_subprocess_fails_closed_without_selection_without_sitecustomize(
        self,
        tmp_path: Path,
    ) -> None:
        """A real child rejects a missing public selection before it builds production assembly."""
        request: SloTuiAssemblyChildProcessRequestDAO = SloTuiAssemblyChildProcessRequestDAO(
            argv=(
                sys.executable,
                "-m",
                "src.tui.assembly.child_process",
                "--workdir",
                str(tmp_path),
            ),
            environment={"PYTHONPATH": str(Path(__file__).parents[3])},
            cwd=tmp_path,
        )

        result = DefaultSloTuiAssemblyChildProcessRunner().run(request=request)

        assert "sitecustomize" not in request.environment["PYTHONPATH"]
        assert result.exit_code == 2
        assert result.reaped is True
