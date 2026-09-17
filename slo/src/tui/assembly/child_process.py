"""Public child-process boundary for the closed current-TUI assembly selection."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from src.agents.slo_agent.orchestrator.spawn_env import build_headless_child_env
from src.tui.assembly.dao import SloTuiAssemblyConfigDAO, SloTuiEnvironmentScenario

__all__ = [
    "SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO",
    "DefaultSloTuiAssemblyChildProcessLauncher",
    "DefaultSloTuiAssemblyChildProcessRunner",
    "SloTuiAssemblyChildProcessLauncher",
    "SloTuiAssemblyChildProcessRequestDAO",
    "SloTuiAssemblyChildProcessResultDAO",
    "SloTuiAssemblyChildRunner",
    "SloTuiAssemblyChildSelectionError",
]

SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO: str = "SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO"
"""The sole safe environment value that carries a validated child scenario."""

_PACKAGE_ROOT: Path = Path(__file__).resolve().parents[3]
"""Directory that makes the installed or source ``src`` package importable by a child."""


class SloTuiAssemblyChildSelectionError(ValueError):
    """Report a missing or invalid child selection before interactive assembly begins."""


class SloTuiAssemblyChildProcessRequestDAO(BaseModel):
    """Carry an already-sanitized public child-process launch request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    argv: tuple[str, ...]
    environment: dict[str, str]
    cwd: Path


class SloTuiAssemblyChildProcessResultDAO(BaseModel):
    """Report the reaped child process terminal state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exit_code: int
    reaped: bool


class SloTuiAssemblyChildProcessLauncher(Protocol):
    """Build a public process request from one validated assembly configuration."""

    def build_request(self, *, config: SloTuiAssemblyConfigDAO) -> SloTuiAssemblyChildProcessRequestDAO:
        """Build a sanitized, behavior-compatible child request.

        Args:
            config (SloTuiAssemblyConfigDAO): Validated current-TUI assembly configuration.

        Returns:
            SloTuiAssemblyChildProcessRequestDAO: Child argv, environment, and working directory.
        """
        ...


class _SloTuiAssemblyFactory(Protocol):
    """Run the current Slo TUI from a validated assembly configuration."""

    def run(self, *, config: SloTuiAssemblyConfigDAO) -> None:
        """Assemble and run one current TUI instance.

        Args:
            config (SloTuiAssemblyConfigDAO): Validated closed assembly configuration.
        """
        ...


class DefaultSloTuiAssemblyChildProcessLauncher:
    """Build sanitized child launches for the single current Textual scenario."""

    def build_request(self, *, config: SloTuiAssemblyConfigDAO) -> SloTuiAssemblyChildProcessRequestDAO:
        """Build public child argv and an environment containing only the validated selection.

        WHAT: Converts one frozen assembly config into a process request without reading an
            alternate environment selection or constructing credentials, a provider, session, or app.
        WHO: A parent process uses this launcher when it needs a separately owned current TUI child.
        WHEN: After CLI scenario selection and before the child process is started.

        Args:
            config (SloTuiAssemblyConfigDAO): Frozen, validated current-TUI assembly configuration.

        Returns:
            SloTuiAssemblyChildProcessRequestDAO: Sanitized launch request with compatible arguments.

        Raises:
            SloTuiAssemblyChildSelectionError: If a bypassed DAO instance is not the closed scenario.
        """
        self._validate_config(config=config)
        environment: dict[str, str] = build_headless_child_env(
            extra={SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO: config.environment_scenario}
        )
        self._add_package_root(environment=environment)
        return SloTuiAssemblyChildProcessRequestDAO(
            argv=self._build_argv(config=config),
            environment=environment,
            cwd=config.workdir,
        )

    @staticmethod
    def _validate_config(*, config: SloTuiAssemblyConfigDAO) -> None:
        """Reject a bypassed configuration before environment or process construction.

        WHAT: Defensively enforces the one child-launch selection and resolved path contract.
        WHO: build_request calls this before it reads parent environment variables or builds argv.
        WHEN: At the public parent-to-child selection boundary.

        Args:
            config (SloTuiAssemblyConfigDAO): Candidate immutable current-TUI configuration.

        Raises:
            SloTuiAssemblyChildSelectionError: If the scenario or path facts are not valid for a child.
        """
        if config.environment_scenario != "textual_current":
            raise SloTuiAssemblyChildSelectionError("unsupported Slo TUI child environment scenario")
        if not config.workdir.is_absolute():
            raise SloTuiAssemblyChildSelectionError("child interactive workdir must be resolved and absolute")
        if config.workspace_file is not None and not config.workspace_file.is_absolute():
            raise SloTuiAssemblyChildSelectionError(
                "child interactive workspace file must be resolved and absolute"
            )

    @staticmethod
    def _add_package_root(*, environment: dict[str, str]) -> None:
        """Make Slo's installed or source package importable without a test preloader.

        WHAT: Adds this module's package root to the child import path while preserving any
            independently allowlisted parent path entries.
        WHO: ``build_request`` calls this after it has constructed the sanitized environment.
        WHEN: Before the child starts, after closed scenario validation and before argv execution.

        Args:
            environment (dict[str, str]): Sanitized environment that will be passed to the child.
        """
        existing_pythonpath: str = environment.get("PYTHONPATH", "")
        package_root: str = str(_PACKAGE_ROOT)
        existing_entries: list[str] = [entry for entry in existing_pythonpath.split(os.pathsep) if entry]
        if package_root in existing_entries:
            return
        environment["PYTHONPATH"] = os.pathsep.join([package_root, *existing_entries])

    @staticmethod
    def _build_argv(*, config: SloTuiAssemblyConfigDAO) -> tuple[str, ...]:
        """Build behavior-compatible command-line arguments for the child runner.

        WHAT: Serializes only resolved public CLI facts; the scenario remains in the sanitized
            environment so a child has one explicit configuration-selection input.
        WHO: build_request calls this while forming a launch request.
        WHEN: Before any subprocess is created.

        Args:
            config (SloTuiAssemblyConfigDAO): Frozen, validated current-TUI assembly configuration.

        Returns:
            tuple[str, ...]: Interpreter, module, and preserved resolved CLI arguments.
        """
        argv: list[str] = [
            sys.executable,
            "-m",
            "src.tui.assembly.child_process",
            "--workdir",
            str(config.workdir),
        ]
        if config.workspace_file is not None:
            argv.extend(["--workspace-file", str(config.workspace_file)])
        if config.resume_session_id is not None:
            argv.extend(["--resume-session-id", config.resume_session_id])
        for plugin_path in config.plugin_paths:
            argv.extend(["--plugin-path", str(plugin_path)])
        return tuple(argv)


class DefaultSloTuiAssemblyChildProcessRunner:
    """Spawn one public child request and wait until its process handle is reaped."""

    def run(self, *, request: SloTuiAssemblyChildProcessRequestDAO) -> SloTuiAssemblyChildProcessResultDAO:
        """Run a child with its sanitized environment and return its reaped exit code.

        WHAT: Starts one child from an immutable request and always waits for it before returning.
        WHO: A parent orchestration or process owner uses this runner after building a request.
        WHEN: Only after a closed selection has been explicitly propagated by the launcher.

        Args:
            request (SloTuiAssemblyChildProcessRequestDAO): Sanitized child process request.

        Returns:
            SloTuiAssemblyChildProcessResultDAO: Child terminal exit code with reaping confirmation.
        """
        completed: subprocess.CompletedProcess[str] = subprocess.run(
            args=request.argv,
            cwd=request.cwd,
            env=request.environment,
            check=False,
            text=True,
        )
        return SloTuiAssemblyChildProcessResultDAO(exit_code=completed.returncode, reaped=True)


class SloTuiAssemblyChildRunner:
    """Consume the public selection boundary before creating current-TUI collaborators."""

    def __init__(self, *, assembly_factory: _SloTuiAssemblyFactory | None = None) -> None:
        """Store an optional assembly delegate without constructing downstream runtime objects.

        WHAT: Retains an injected test collaborator or defers production factory construction.
        WHO: module main and focused child-process tests create this public runner.
        WHEN: Before selection validation; production construction occurs only after that validation passes.

        Args:
            assembly_factory (_SloTuiAssemblyFactory | None): Optional current-TUI factory.
                Defaults to None.
        """
        self._assembly_factory: _SloTuiAssemblyFactory | None = assembly_factory

    def run(self, *, arguments: Sequence[str], environment: Mapping[str, object]) -> int:
        """Validate selection and resolved child arguments before invoking current-TUI assembly.

        WHAT: Parses behavior-compatible child facts and rejects missing, malformed, forged, or
            unknown selection values before credential, provider, session, or app construction.
        WHO: module main and direct child-process tests call this public runner.
        WHEN: First operation in every separately launched current-TUI child.

        Args:
            arguments (Sequence[str]): Public child command arguments excluding the interpreter/module.
            environment (Mapping[str, object]): Sanitized child environment supplied by the parent.

        Returns:
            int: Zero after the selected current assembly completes normally.

        Raises:
            SloTuiAssemblyChildSelectionError: If the selection or resolved child facts are invalid.
        """
        scenario: SloTuiEnvironmentScenario = self._select_scenario(environment=environment)
        config: SloTuiAssemblyConfigDAO = self._build_config(arguments=arguments, scenario=scenario)
        assembly_factory: _SloTuiAssemblyFactory = self._resolve_assembly_factory()
        assembly_factory.run(config=config)
        return 0

    def _resolve_assembly_factory(self) -> _SloTuiAssemblyFactory:
        """Return an injected factory or construct production assembly after fail-closed validation.

        WHAT: Defers importing and wiring current presentation collaborators until selection and
            child arguments have both validated.
        WHO: run calls this immediately before it delegates the frozen configuration.
        WHEN: After every local validation gate and before the first preference, session, or app action.

        Returns:
            _SloTuiAssemblyFactory: Injected test factory or unstarted production factory.
        """
        if self._assembly_factory is not None:
            return self._assembly_factory
        from src.tui.assembly.factory import DefaultSloTuiAssemblyFactory

        return DefaultSloTuiAssemblyFactory.build_default()

    @staticmethod
    def _select_scenario(*, environment: Mapping[str, object]) -> SloTuiEnvironmentScenario:
        """Select the one valid child scenario without coercing hostile environment values.

        WHAT: Treats the selection environment variable as an exact closed allowlist value.
        WHO: run calls this before parsing child facts or touching the assembly factory.
        WHEN: First validation gate in a current-TUI child process.

        Args:
            environment (Mapping[str, object]): Sanitized child environment candidate.

        Returns:
            SloTuiEnvironmentScenario: The only permitted current Textual selection.

        Raises:
            SloTuiAssemblyChildSelectionError: If selection is absent, non-string, or not allowlisted.
        """
        selection: object = environment.get(SLO_TUI_ASSEMBLY_ENVIRONMENT_SCENARIO)
        if selection != "textual_current" or not isinstance(selection, str):
            raise SloTuiAssemblyChildSelectionError("invalid Slo TUI child environment scenario")
        return "textual_current"

    @staticmethod
    def _build_config(
        *, arguments: Sequence[str], scenario: SloTuiEnvironmentScenario
    ) -> SloTuiAssemblyConfigDAO:
        """Parse resolved child facts into the frozen public assembly configuration.

        WHAT: Rebuilds the existing CLI facts after scenario validation without resolving preferences.
        WHO: run calls this before it invokes the current assembly factory.
        WHEN: After closed selection succeeds and before every downstream runtime collaborator.

        Args:
            arguments (Sequence[str]): Behavior-compatible child arguments.
            scenario (SloTuiEnvironmentScenario): Validated closed scenario.

        Returns:
            SloTuiAssemblyConfigDAO: Frozen configuration ready for current assembly.

        Raises:
            SloTuiAssemblyChildSelectionError: If arguments are malformed or do not satisfy DAO validation.
        """
        parser: argparse.ArgumentParser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--workdir", required=True)
        parser.add_argument("--workspace-file")
        parser.add_argument("--resume-session-id")
        parser.add_argument("--plugin-path", action="append", default=[])
        try:
            parsed: argparse.Namespace = parser.parse_args(args=list(arguments))
            return SloTuiAssemblyConfigDAO(
                environment_scenario=scenario,
                workdir=Path(parsed.workdir),
                workspace_file=Path(parsed.workspace_file) if parsed.workspace_file is not None else None,
                resume_session_id=parsed.resume_session_id,
                plugin_paths=tuple(Path(path) for path in parsed.plugin_path),
            )
        except (SystemExit, ValidationError, ValueError) as error:
            raise SloTuiAssemblyChildSelectionError("invalid Slo TUI child assembly arguments") from error


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the public child entry point with the process environment.

    WHAT: Defers production factory construction until the child validates its explicit selection.
    WHO: Python's ``-m src.tui.assembly.child_process`` module execution calls this function.
    WHEN: At child-process startup, before preferences, credentials, providers, sessions, or applications.

    Args:
        arguments (Sequence[str] | None): Optional testable argument sequence. Defaults to process argv.

    Returns:
        int: Child exit code for normal completion or a fail-closed configuration error.
    """
    runner: SloTuiAssemblyChildRunner = SloTuiAssemblyChildRunner()
    try:
        return runner.run(arguments=sys.argv[1:] if arguments is None else arguments, environment=os.environ)
    except SloTuiAssemblyChildSelectionError:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
