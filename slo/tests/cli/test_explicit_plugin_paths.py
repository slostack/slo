"""CLI propagation coverage for repeatable explicit Feature 75 plugin paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from src.cli.app import app

runner: CliRunner = CliRunner()


def test_tui_repeatable_plugin_option_preserves_argument_order(tmp_path: Path) -> None:
    """Bare TUI launch forwards repeatable ``--plugin`` paths to dispatch unchanged."""
    first: Path = tmp_path / "first.py"
    second: Path = tmp_path / "second.py"

    with patch("src.cli.app.TyperDispatch.tui") as dispatch:
        result = runner.invoke(app, ["--plugin", str(first), "--plugin", str(second)])

    assert result.exit_code == 0
    assert dispatch.call_args.kwargs["plugin_paths"] == [first, second]


def test_headless_repeatable_plugin_option_preserves_argument_order(tmp_path: Path) -> None:
    """Headless launch forwards repeatable ``--plugin`` paths to dispatch unchanged."""
    first: Path = tmp_path / "first.py"
    second: Path = tmp_path / "second.py"

    with patch("src.cli.app.TyperDispatch.run_headless", return_value=0) as dispatch:
        result = runner.invoke(
            app,
            ["run", "--prompt", "hi", "--plugin", str(first), "--plugin", str(second)],
        )

    assert result.exit_code == 0
    assert dispatch.call_args.kwargs["plugin_paths"] == [first, second]
