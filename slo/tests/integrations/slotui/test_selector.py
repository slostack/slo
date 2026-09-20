"""Tests for explicit Slotui selection without a runtime Slotui import."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cli.app import app
from src.cli.typer_dispatch import TyperDispatch
from typer.testing import CliRunner
from src.integrations.slotui.dao import SlotuiCoreArtifactReferenceDAO
from src.integrations.slotui.selector import SlotuiCoreUnavailableError, SlotuiPresentationSelector


def test_select_when_textual_current_preserves_default_without_reading_core_reference() -> None:
    """Keep the established Textual route selected unless an operator opts in."""
    selected = SlotuiPresentationSelector.select(
        presentation="textual_current",
        core_reference_path=None,
    )

    assert selected.presentation == "textual_current"
    assert selected.core_installation_plan is None


def test_select_when_slotui_core_is_requested_without_reference_fails_closed() -> None:
    """Reject explicit Slotui selection until a verified core artifact is supplied."""
    with pytest.raises(SlotuiCoreUnavailableError, match="verified Slotui core wheel is unavailable"):
        SlotuiPresentationSelector.select(presentation="slotui_core", core_reference_path=None)


def test_select_when_slotui_core_reference_is_verified_returns_installation_plan(tmp_path: Path) -> None:
    """Return a local no-index installation plan without importing or installing Slotui."""
    reference_path: Path = _write_core_reference_fixture(tmp_path=tmp_path)

    selected = SlotuiPresentationSelector.select(
        presentation="slotui_core",
        core_reference_path=reference_path,
    )

    assert selected.presentation == "slotui_core"
    assert selected.core_installation_plan is not None
    assert selected.core_installation_plan.argv[5:] == (
        "--no-index",
        "--no-deps",
        str(tmp_path / "slotui-0.1.0-py3-none-any.whl"),
    )


def test_tui_when_default_option_keeps_current_textual_assembly(tmp_path: Path) -> None:
    """Retain the exact default assembly configuration and never inspect Slotui."""
    with (
        patch("src.cli.typer_dispatch.interactive_logging"),
        patch("src.cli.typer_dispatch._build_default_tui_assembly_factory") as build_factory,
    ):
        TyperDispatch.tui(workdir=tmp_path)

    build_factory.assert_called_once_with()


def test_cli_when_slotui_core_requested_forwards_explicit_opt_in_to_dispatch() -> None:
    """Forward only explicit nondefault presentation facts through the parse surface."""
    runner: CliRunner = CliRunner()
    with patch("src.cli.app.TyperDispatch.tui") as tui:
        result = runner.invoke(app, ["--presentation", "slotui_core"])

    assert result.exit_code == 0
    tui.assert_called_once_with(
        workdir=None,
        workspace_file=None,
        resume_session_reference=None,
        presentation="slotui_core",
        slotui_core_reference=None,
    )


def test_tui_when_slotui_core_requested_and_unavailable_returns_user_clear_error(tmp_path: Path) -> None:
    """Fail before current TUI assembly when the opt-in wheel proof cannot verify."""
    with pytest.raises(SlotuiCoreUnavailableError, match="Slotui core was requested"):
        TyperDispatch.tui(
            workdir=tmp_path,
            presentation="slotui_core",
            slotui_core_reference=tmp_path / "missing-reference.json",
        )


def test_headless_when_slotui_core_requested_never_selects_interactive_presentation() -> None:
    """Reject a presentation option on the headless route rather than silently switching it."""
    with pytest.raises(ValueError, match="presentation selection applies only to interactive"):
        TyperDispatch.run_headless(prompt="headless", presentation="slotui_core")


def _write_core_reference_fixture(*, tmp_path: Path) -> Path:
    """Create digest-pinned manifest/reference fixtures without a real Slotui distribution."""
    wheel_path: Path = tmp_path / "slotui-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        archive.writestr("slotui/__init__.py", "raise AssertionError('no import')\n")
        archive.writestr(
            "slotui-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: slotui\nVersion: 0.1.0\n",
        )
        archive.writestr(
            "slotui-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    capabilities: dict[str, list[str]] = {
        "terminal": ["TerminalDriver"],
        "editor": ["EditorComponent"],
        "events": ["AgentStreamEventDAO"],
        "session": ["AgentSession"],
        "history": ["SessionHistoryEventDAO"],
        "replay": ["TranscriptEntryDAO"],
        "slash": ["SlashRouter"],
        "live_transcript": ["LiveTranscript"],
    }
    manifest_payload: dict[str, object] = {
        "schema_version": "slotui-core-release-manifest-v1",
        "distribution_name": "slotui",
        "version": "0.1.0",
        "wheel_filename": wheel_path.name,
        "wheel_sha256": hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
        "wheel_artifact": {"source": wheel_path.as_uri()},
        "export_surface": sorted({item for values in capabilities.values() for item in values}),
        "capabilities": [
            {"name": name, "required_exports": exports} for name, exports in capabilities.items()
        ],
    }
    manifest_bytes: bytes = json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    manifest_path: Path = tmp_path / "slotui-core-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    reference = SlotuiCoreArtifactReferenceDAO(
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    reference_path: Path = tmp_path / "slotui-core-reference.json"
    reference_path.write_text(reference.model_dump_json(), encoding="utf-8")
    return reference_path
