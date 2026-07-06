"""Typer CLI for slo — default subcommand opens the TUI (sub-spec 02.a.4)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
import typer
import typer.core

from src.cli.typer_dispatch import TyperDispatch
from src.cli.version import resolve_version


__all__ = ["app", "main"]


class _SloGroup(typer.core.TyperGroup):
    """Custom group so ``slo <subcommand>`` wins over the workdir positional.

    Click's default ``Group.parse_args`` lets the optional positional
    ``Argument`` greedily consume the first token, even when that token
    names a known subcommand. That makes ``slo serve --port 8000`` fail —
    ``serve`` is swallowed as the workdir and ``--port`` becomes an
    unknown option on the group.

    This override checks the first non-option token: if it names a known
    subcommand, the group skips its own positional parsing and hands the
    subcommand straight through to Click's dispatch. Otherwise the
    default behaviour kicks in and the token is parsed as the workdir.
    """

    def parse_args(
        self,
        ctx: click.Context,
        args: list[str],
    ) -> list[str]:
        """Disambiguate workdir-vs-subcommand on the first positional.

        Args:
            ctx (click.Context): The active Click context.
            args (list[str]): The raw argument list.

        Returns:
            list[str]: The remaining ``ctx.args`` after group-level
                parsing — Click's standard return shape.
        """
        first_positional_index: Optional[int] = next(
            (i for i, token in enumerate(args) if not token.startswith("-")),
            None,
        )
        if (
            first_positional_index is not None
            and args[first_positional_index] in self.commands
        ):
            head: list[str] = args[:first_positional_index]
            tail: list[str] = args[first_positional_index:]
            super().parse_args(ctx, head)
            # Click 8.x reads ``ctx._protected_args`` (private) in
            # ``MultiCommand.invoke``; the public ``protected_args`` alias
            # is read-only. Set the underscored attribute directly so the
            # group dispatches the subcommand instead of treating the run
            # as bare.
            ctx._protected_args = tail[:1]
            ctx.args = tail[1:]
            return ctx.args
        return super().parse_args(ctx, args)


app: typer.Typer = typer.Typer(
    name="slo",
    help="Slo — in-process ReAct coding agent. Run `slo` to open the TUI.",
    no_args_is_help=False,
    add_completion=False,
    cls=_SloGroup,
)


@app.callback(invoke_without_command=True)
def _default(
    ctx: typer.Context,
    workdir: Optional[Path] = typer.Argument(
        None,
        help="Directory to scope the TUI to (defaults to the current working directory).",
    ),
    resume: Optional[str] = typer.Option(
        None,
        "--resume",
        help="Resume a known Slo session reference (session id or unique session name).",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help=(
            "Path to a VSCode .code-workspace file. Every declared folder contributes "
            "its SLO.md / AGENTS.md / CLAUDE.md files to the system prompt."
        ),
    ),
    version: bool = typer.Option(
        False,
        "--version",
        help="Print the package version and exit.",
        is_eager=True,
    ),
) -> None:
    """Bare ``slo`` (or ``slo <dir>``) opens the TUI. ``--version`` exits early."""
    if version:
        typer.echo(message=resolve_version())
        raise typer.Exit(code=0)
    if ctx.invoked_subcommand is not None:
        return
    TyperDispatch.tui(
        workdir=workdir,
        workspace_file=workspace,
        resume_session_reference=resume,
    )


@app.command(name="run")
def _run(
    prompt: str = typer.Option(
        ...,
        "--prompt",
        "-p",
        help="Prompt to run once, headless.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit one AgentStreamEventDAO JSON object per stdout line.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model override (e.g. claude-opus-4-5).",
    ),
    reasoning: Optional[str] = typer.Option(
        None,
        "--reasoning",
        help="Reasoning level override (off / minimal / low / medium / high / xhigh).",
    ),
    cwd: Optional[str] = typer.Option(
        None,
        "--cwd",
        help="Working directory for the run (defaults to the current directory).",
    ),
    enable_history: bool = typer.Option(
        False,
        "--enable-history",
        help="Persist the session history to disk (off by default for headless runs).",
    ),
    resume: Optional[str] = typer.Option(
        None,
        "--resume",
        help="Resume a known Slo session reference (session id or unique session name). Implies --enable-history.",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        help=(
            "Path to a VSCode .code-workspace file. Every declared folder contributes "
            "its SLO.md / AGENTS.md / CLAUDE.md files to the system prompt."
        ),
    ),
    session_id: Optional[str] = typer.Option(
        None,
        "--session-id",
        help=(
            "Explicit session id for this run (UUID4 or slug matching [A-Za-z0-9._-]+). "
            "Falls back to SLO_SESSION_ID env, then a fresh UUID4."
        ),
    ),
    system_prompt_file: Optional[Path] = typer.Option(
        None,
        "--system-prompt-file",
        help="Path to a file whose content fully replaces the default system prompt.",
    ),
    append_system_prompt_file: Optional[Path] = typer.Option(
        None,
        "--append-system-prompt-file",
        help="Path to a file whose content is appended after the default system prompt.",
    ),
    orchestrator_mode: bool = typer.Option(
        False,
        "--orchestrator/--no-orchestrator",
        help="Attach a sub-agent pool before running so this agent can spawn sub-agents.",
    ),
    system_prompt_b64: Optional[str] = typer.Option(
        None,
        "--system-prompt-b64",
        help="Base64-encoded system prompt override for this run.",
    ),
) -> None:
    """Run one agent loop with no UI, stream JSONL to stdout, then exit."""
    exit_code: int = TyperDispatch.run_headless(
        prompt=prompt,
        as_json=as_json,
        model=model,
        reasoning=reasoning,
        cwd=cwd,
        enable_history=enable_history,
        resume=resume,
        workspace=workspace,
        explicit_session_id=session_id,
        system_prompt_file=system_prompt_file,
        append_system_prompt_file=append_system_prompt_file,
        orchestrator_mode=orchestrator_mode,
        system_prompt_b64=system_prompt_b64,
    )
    raise typer.Exit(code=exit_code)


@app.command(name="serve")
def _serve(
    port: int = typer.Option(
        7700,
        "--port",
        help="Port to bind the FastAPI health-check app to.",
    ),
) -> None:
    """Run the FastAPI ``/healthz``-only app via uvicorn."""
    TyperDispatch.serve(port=port)


@app.command(name="visualize")
def _visualize(
    session: str = typer.Option(
        ...,
        "--session",
        "-s",
        help="Session id or unique session name to inspect.",
    ),
    follow: bool = typer.Option(
        True,
        "--follow/--no-follow",
        help="Poll for live updates while the workflow is running.",
    ),
    refresh_seconds: float = typer.Option(
        1.0,
        "--refresh-seconds",
        help="Polling cadence in seconds (requires --follow).",
    ),
    detail_format: str = typer.Option(
        "textual",
        "--detail-format",
        help="Transcript rendering mode: textual | markdown | html.",
    ),
) -> None:
    """Open a read-only TUI to inspect a headless workflow run."""
    TyperDispatch.visualize(
        session_reference=session,
        follow=follow,
        refresh_seconds=refresh_seconds,
        detail_format=detail_format,
    )


@app.command(name="update")
def _update(
    development: bool = typer.Option(
        False,
        "--development",
        help="Track ``main`` instead of pinning to the latest release.",
    ),
    ref: Optional[str] = typer.Option(
        None,
        "--ref",
        help="Install an explicit branch / tag / commit (overrides --development).",
    ),
) -> None:
    """Reinstall slo via pipx: latest release by default, ``main`` with ``--development``, or an explicit ``--ref``."""
    TyperDispatch.update(development=development, ref=ref)


def main() -> int:
    """Console-script entry point.

    Returns:
        int: The process exit code (always ``0`` — Typer raises ``SystemExit``
            on error, which bypasses this return).
    """
    app()
    return 0
