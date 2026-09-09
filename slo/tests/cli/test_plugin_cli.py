"""CLI-surface tests for managed plugin lifecycle commands (Feature 75.a.4)."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from src.cli.app import app

runner: CliRunner = CliRunner()


def test_plugin_install_delegates_confirmed_source() -> None:
    """``slo plugin install --yes`` delegates through the dispatch gateway."""
    with patch("src.cli.plugin.TyperDispatch.plugin", return_value="installed acme-tools") as dispatch:
        result = runner.invoke(
            app,
            ["plugin", "install", "https://github.com/acme/tools", "--yes"],
        )

    assert result.exit_code == 0
    assert result.stdout.strip() == "installed acme-tools"
    dispatch.assert_called_once_with(
        action="install",
        source_url="https://github.com/acme/tools",
        plugin_id=None,
        confirmed=True,
    )


def test_plugin_install_without_yes_surfaces_confirmation_refusal() -> None:
    """An unconfirmed new source returns the dispatch refusal without installation."""
    with patch(
        "src.cli.plugin.TyperDispatch.plugin",
        side_effect=ValueError("requires operator confirmation; re-run with --yes"),
    ) as dispatch:
        result = runner.invoke(app, ["plugin", "install", "https://github.com/acme/tools"])

    assert result.exit_code == 1
    assert "--yes" in result.stderr
    dispatch.assert_called_once_with(
        action="install",
        source_url="https://github.com/acme/tools",
        plugin_id=None,
        confirmed=False,
    )


def test_plugin_installs_bundled_bash_renderer_through_dispatch() -> None:
    """The explicit bundled delivery trigger delegates to the installer gateway."""
    with patch("src.cli.plugin.TyperDispatch.plugin", return_value="installed bundled slo-slo") as dispatch:
        result = runner.invoke(app, ["plugin", "install-bundled-bash-live-output"])

    assert result.exit_code == 0
    dispatch.assert_called_once_with(
        action="install_bundled_bash_live_output",
        source_url=None,
        plugin_id=None,
        confirmed=False,
    )


def test_plugin_list_delegates_and_renders_provenance() -> None:
    """``slo plugin list`` prints the dispatcher-provided install rows."""
    row: str = "acme-tools deadbeef https://github.com/acme/tools"
    with patch("src.cli.plugin.TyperDispatch.plugin", return_value=row) as dispatch:
        result = runner.invoke(app, ["plugin", "list"])

    assert result.exit_code == 0
    assert row in result.stdout
    dispatch.assert_called_once_with(
        action="list",
        source_url=None,
        plugin_id=None,
        confirmed=False,
    )


def test_plugin_uninstall_delegates_plugin_id() -> None:
    """``slo plugin uninstall`` delegates its target id through dispatch."""
    with patch("src.cli.plugin.TyperDispatch.plugin", return_value="uninstalled acme-tools") as dispatch:
        result = runner.invoke(app, ["plugin", "uninstall", "acme-tools"])

    assert result.exit_code == 0
    dispatch.assert_called_once_with(
        action="uninstall",
        source_url=None,
        plugin_id="acme-tools",
        confirmed=False,
    )


def test_plugin_upgrade_delegates_plugin_id() -> None:
    """``slo plugin upgrade`` delegates its target id through dispatch."""
    with patch("src.cli.plugin.TyperDispatch.plugin", return_value="upgraded acme-tools") as dispatch:
        result = runner.invoke(app, ["plugin", "upgrade", "acme-tools"])

    assert result.exit_code == 0
    dispatch.assert_called_once_with(
        action="upgrade",
        source_url=None,
        plugin_id="acme-tools",
        confirmed=False,
    )
