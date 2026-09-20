"""Tests for explicit Slotui selection without a runtime Slotui import or fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.app import app
from src.cli.typer_dispatch import TyperDispatch
from src.integrations.slotui.selector import SlotuiCoreUnavailableError, SlotuiPresentationSelector
from tests.integrations.slotui.test_core_contract import (
    _finalize_manifest_hash,
    _manifest_payload,
    _write_reference,
    _write_wheel_fixture,
)


def test_select_when_textual_current_preserves_default_without_reading_core_reference() -> None:
    """Keep the established Textual route selected unless an operator opts in.

    The selector intentionally has no default core discovery behavior.
    """
    selected = SlotuiPresentationSelector.select(
        presentation="textual_current",
        core_reference_path=None,
    )

    assert selected.presentation == "textual_current"
    assert selected.core_verification_receipt is None


def test_select_when_slotui_core_is_requested_without_reference_fails_closed() -> None:
    """Reject explicit Slotui selection until protected CI provides an adapter fixture reference."""
    with pytest.raises(SlotuiCoreUnavailableError, match="verified Slotui core wheel is unavailable"):
        SlotuiPresentationSelector.select(presentation="slotui_core", core_reference_path=None)


def test_select_when_slotui_core_reference_is_verified_still_fails_before_textual_fallback(
    tmp_path: Path,
) -> None:
    """Stop after static proof because no Slotui presentation assembly exists in Slo yet."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference_path: Path = tmp_path / "slotui-core-reference.json"
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    reference_path.write_text(reference.model_dump_json(), encoding="utf-8")

    with pytest.raises(
        SlotuiCoreUnavailableError, match="wheel was verified.*integration is not available yet"
    ):
        SlotuiPresentationSelector.select(presentation="slotui_core", core_reference_path=reference_path)


def test_tui_when_default_option_keeps_current_textual_assembly(tmp_path: Path) -> None:
    """Retain the exact default assembly configuration and never inspect Slotui fixtures."""
    factory: MagicMock = MagicMock()
    with (
        patch("src.cli.typer_dispatch.interactive_logging"),
        patch(
            "src.cli.typer_dispatch._build_default_tui_assembly_factory", return_value=factory
        ) as build_factory,
    ):
        TyperDispatch.tui(workdir=tmp_path)

    build_factory.assert_called_once_with()
    factory.run.assert_called_once()


def test_tui_when_verified_slotui_core_requested_never_invokes_textual_factory_or_session(
    tmp_path: Path,
) -> None:
    """Prove the dispatcher end-to-end guard runs before the current assembly factory/session route."""
    wheel_path: Path = _write_wheel_fixture(tmp_path=tmp_path)
    payload: dict[str, object] = _manifest_payload(wheel_path=wheel_path)
    _finalize_manifest_hash(payload=payload)
    reference = _write_reference(tmp_path=tmp_path, payload=payload)
    reference_path: Path = tmp_path / "slotui-core-reference.json"
    reference_path.write_text(reference.model_dump_json(), encoding="utf-8")

    with (
        patch("src.cli.typer_dispatch._build_default_tui_assembly_factory") as build_factory,
        patch("src.cli.typer_dispatch.SloTuiAssemblyConfigDAO") as assembly_config,
        pytest.raises(SlotuiCoreUnavailableError, match="wheel was verified.*not available yet"),
    ):
        TyperDispatch.tui(
            workdir=tmp_path,
            presentation="slotui_core",
            slotui_core_reference=reference_path,
        )

    build_factory.assert_not_called()
    assembly_config.assert_not_called()


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


def test_headless_when_slotui_core_requested_never_selects_interactive_presentation() -> None:
    """Reject a presentation option on headless execution without starting a runner."""
    with pytest.raises(ValueError, match="presentation selection applies only to interactive"):
        TyperDispatch.run_headless(prompt="headless", presentation="slotui_core")
