"""Typer sub-app ``slo channel`` — talk to Slo agents from any program (108.5 §5).

Parsing only; ``src/cli/channel_dispatch.py`` does the work and owns the exit
codes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from src.cli.channel_dispatch import ChannelDispatch

__all__ = ["channel_app"]


channel_app: typer.Typer = typer.Typer(
    name="channel",
    help="Talk to Slo agents through the channel queue, or run a channel adapter.",
    add_completion=False,
    no_args_is_help=True,
)


@channel_app.command(name="agents")
def agents_command() -> None:
    """List open agents: id prefix, name, last seen."""
    raise typer.Exit(code=ChannelDispatch.agents())


@channel_app.command(name="send")
def send_command(
    text: str = typer.Argument(..., help="Prompt text (quote it; use -- before text starting with '-')."),
    to: str = typer.Option(..., "--to", help="Agent id prefix, as shown by `slo channel agents`."),
    force: bool = typer.Option(False, "--force", help="Force it into the agent's current run."),
    wait: bool = typer.Option(
        False, "--wait", help="Print the reply (or, with --force, the acceptance) before exiting."
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", min=0.0, help="Seconds --wait waits (default 300). Exit 124 on timeout."
    ),
) -> None:
    """Send TEXT as `$USER (cli)`. Exit 0 sent/replied · 3 closed · 5 unknown · 124 timeout."""
    raise typer.Exit(code=ChannelDispatch.send(to=to, text=text, force=force, wait=wait, timeout=timeout))


@channel_app.command(name="follow")
def follow_command(
    to: str = typer.Option(..., "--to", help="Agent id prefix, as shown by `slo channel agents`."),
    history: int = typer.Option(20, "--history", min=0, help="Earlier messages to show first."),
) -> None:
    """Stream an agent's conversation until it finishes (Ctrl+C to stop)."""
    raise typer.Exit(code=ChannelDispatch.follow(to=to, history=history))


@channel_app.command(name="run")
def run_command(
    name: Optional[str] = typer.Argument(None, help="Built-in adapter to run: telegram."),
    adapter: Optional[str] = typer.Option(
        None, "--adapter", help="Custom adapter class instead, as pkg.module:ClassName (trusted local code)."
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", help="Built-in adapter config file (default $SLO_HOME/channels/<name>.json)."
    ),
) -> None:
    """Run one channel adapter in the foreground until SIGINT/SIGTERM. Exit 0 · 1 config error."""
    raise typer.Exit(code=ChannelDispatch.run_adapter(builtin=name, reference=adapter, config_path=config))
