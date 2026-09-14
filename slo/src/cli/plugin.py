"""Managed-plugin lifecycle Typer sub-application (Feature 75.a.4)."""

from __future__ import annotations

import typer

from src.cli.typer_dispatch import TyperDispatch

__all__ = ["plugin_app"]

plugin_app: typer.Typer = typer.Typer(
    help="Install, inspect, upgrade, and remove managed Slo plugins.",
    no_args_is_help=True,
)


@plugin_app.command(name="install")
def install(
    source_url: str = typer.Argument(..., help="HTTPS GitHub or GitLab plugin source URL."),
    yes: bool = typer.Option(False, "--yes", help="Confirm trust in a new plugin source."),
) -> None:
    """Install one plugin after explicit source-trust confirmation."""
    _run_action(action="install", source_url=source_url, confirmed=yes)


@plugin_app.command(name="install-bundled-bash-live-output")
def install_bundled_bash_live_output() -> None:
    """Install Slo's bundled Bash live-output renderer through managed installation."""
    _run_action(action="install_bundled_bash_live_output")


@plugin_app.command(name="list")
def list_installed() -> None:
    """List managed plugins with their pinned revisions and source provenance."""
    _run_action(action="list")


@plugin_app.command(name="uninstall")
def uninstall(
    plugin_id: str = typer.Argument(..., help="Installed plugin id to remove."),
) -> None:
    """Remove one managed plugin and its durable install record."""
    _run_action(action="uninstall", plugin_id=plugin_id)


@plugin_app.command(name="upgrade")
def upgrade(
    plugin_id: str = typer.Argument(..., help="Installed plugin id to upgrade."),
) -> None:
    """Fetch and atomically swap one managed plugin to its latest pinned commit."""
    _run_action(action="upgrade", plugin_id=plugin_id)


def _run_action(
    *,
    action: str,
    source_url: str | None = None,
    plugin_id: str | None = None,
    confirmed: bool = False,
) -> None:
    """Delegate one parse-surface action through the CLI dispatch gateway.

    Args:
        action (str): Managed lifecycle command to execute.
        source_url (str | None): Install source when applicable.
        plugin_id (str | None): Existing plugin id when applicable.
        confirmed (bool): Operator confirmation for a new source.
    """
    try:
        result: str = TyperDispatch.plugin(
            action=action,
            source_url=source_url,
            plugin_id=plugin_id,
            confirmed=confirmed,
        )
    except ValueError as exc:
        typer.echo(message=str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(message=result)
