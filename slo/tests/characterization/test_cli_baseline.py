"""Characterize bare CLI workdir, resume, and known-subcommand parsing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from src.cli.app import app
from tests.characterization.baseline_contract import BaselineCaseDAO, BaselineComparator
from tests.characterization.normalizers import normalize_baseline_capture

_BASELINE_ROOT: Path = Path("tests/fixtures/79_tui_v2/baseline")
_FIXTURE_PATH: Path = _BASELINE_ROOT / "cli/bare_workdir_resume_subcommand.json"
_LEDGER_PATH: Path = _BASELINE_ROOT / "baseline-ledger.json"


def test_bare_workdir_resume_and_known_subcommand_match_baseline(tmp_path: Path) -> None:
    """Freeze root workdir/resume parsing and known-subcommand precedence.

    WHAT: Exercises the real Typer parse surface while patching only the
        downstream runtime dispatch that would open an interactive TUI.
    WHO: Slotui migration work uses this as the CLI compatibility baseline.
    WHEN: Before replacement work changes CLI parsing or dispatch assembly.
    """
    runner: CliRunner = CliRunner()
    invocations: list[dict[str, object]] = []

    def record_tui(**kwargs: object) -> None:
        """Record the parsed TUI invocation without starting a terminal app.

        WHAT: Provides the external-runtime seam required to inspect real Typer
            behavior deterministically.
        WHO: The patched TyperDispatch.tui calls it for root CLI invocations.
        WHEN: During this characterization capture only.
        """
        invocations.append(kwargs)

    def record_update(**kwargs: object) -> None:
        """Record the known subcommand dispatch without changing installation state.

        WHAT: Prevents self-update side effects while preserving parser routing.
        WHO: The patched TyperDispatch.update calls it for ``slo update``.
        WHEN: During this characterization capture only.
        """
        invocations.append({"update": kwargs})

    with (
        patch("src.cli.app.TyperDispatch.tui", side_effect=record_tui),
        patch("src.cli.app.TyperDispatch.update", side_effect=record_update),
    ):
        bare = runner.invoke(app, [])
        workdir_resume = runner.invoke(app, ["--resume", "Release Prep", str(tmp_path)])
        known_subcommand = runner.invoke(app, ["update", "--development"])
        subcommand_named_workdir = runner.invoke(app, ["update"])

    capture: dict[str, object] = {
        "bare": {"exit_code": bare.exit_code, "exception": _exception_name(result=bare)},
        "workdir_resume": {
            "exit_code": workdir_resume.exit_code,
            "exception": _exception_name(result=workdir_resume),
        },
        "known_subcommand": {
            "exit_code": known_subcommand.exit_code,
            "exception": _exception_name(result=known_subcommand),
        },
        "subcommand_named_workdir": {
            "exit_code": subcommand_named_workdir.exit_code,
            "exception": _exception_name(result=subcommand_named_workdir),
        },
        "invocations": _jsonable_invocations(invocations=invocations),
    }
    expected: bytes = _FIXTURE_PATH.read_bytes()
    observed: bytes = normalize_baseline_capture(
        capture=_canonical_json_bytes(value=capture),
        case_id="cli-bare-workdir-resume-subcommand",
    )
    case: BaselineCaseDAO = BaselineCaseDAO(
        case_id="cli-bare-workdir-resume-subcommand",
        artifact_path="tests/fixtures/79_tui_v2/baseline/cli/bare_workdir_resume_subcommand.json",
        normalizer_version="v1",
    )
    ledger = BaselineComparator.load_ledger(ledger_path=_LEDGER_PATH)
    BaselineComparator.compare(case=case, observed=observed, expected=expected, ledger=ledger)


def _exception_name(*, result: object) -> str | None:
    """Return a stable exception class name from a Typer result.

    WHAT: Captures parser outcome without preserving volatile traceback paths.
    WHO: The CLI characterization capture calls it for every invocation.
    WHEN: Immediately after CliRunner returns.

    Args:
        result (object): CliRunner result carrying an optional exception.

    Returns:
        str | None: Exception class name, or None for successful parsing.
    """
    exception: BaseException | None = getattr(result, "exception", None)
    return None if exception is None else type(exception).__name__


def _jsonable_invocations(*, invocations: list[dict[str, object]]) -> list[dict[str, object]]:
    """Convert patched dispatch arguments into deterministic JSON primitives.

    WHAT: Retains parsed values while representing Path objects without machine
        temporary roots leaking into the fixture.
    WHO: The CLI characterization test calls it after all invocations finish.
    WHEN: Before the capture passes through the sole normalizer.

    Args:
        invocations (list[dict[str, object]]): Recorded downstream dispatch calls.

    Returns:
        list[dict[str, object]]: JSON-serializable invocation records.
    """
    return [
        {key: _jsonable_value(value=value) for key, value in invocation.items()} for invocation in invocations
    ]


def _jsonable_value(*, value: object) -> object:
    """Represent Path values while preserving all other parsed semantics.

    WHAT: Converts recursive invocation values into JSON-supported primitives.
    WHO: _jsonable_invocations uses it at the dispatch-capture boundary.
    WHEN: Before canonical JSON serialization.

    Args:
        value (object): Captured dispatch argument value.

    Returns:
        object: Equivalent JSON-compatible representation.
    """
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable_value(value=item) for key, item in value.items()}
    return value


def _canonical_json_bytes(*, value: object) -> bytes:
    """Encode a capture using the fixture's deterministic JSON representation.

    WHAT: Produces newline-terminated sorted JSON bytes for byte comparison.
    WHO: Every JSON capture test uses an equivalent local serializer.
    WHEN: Immediately before the direct normalizer call.

    Args:
        value (object): JSON-compatible capture payload.

    Returns:
        bytes: UTF-8 canonical fixture bytes.
    """
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
