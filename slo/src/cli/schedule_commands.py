"""The single `slo schedule` Typer group — flag parsing only, no logic."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import typer
from pydantic import ValidationError

from src.cli.schedule_dispatch import CoalescingMode, ScheduleDispatch, SessionMode
from src.schedules.dao import (
    CronTriggerDAO,
    IntervalTriggerDAO,
    OneShotTriggerDAO,
    TriggerDAO,
)

__all__ = ["schedule_app"]

schedule_app: typer.Typer = typer.Typer(help="Schedule management.")


def _build_trigger(
    *,
    cron: Optional[str],
    interval_seconds: Optional[int],
    run_at: Optional[str],
    tz: str,
) -> TriggerDAO:
    """Build the trigger DAO from exactly one trigger flag.

    Args:
        cron (Optional[str]): The ``--cron`` value.
        interval_seconds (Optional[int]): The ``--interval-seconds`` value.
        run_at (Optional[str]): The raw ``--run-at`` value.
        tz (str): The ``--tz`` value.

    Returns:
        TriggerDAO: The matching trigger.

    Raises:
        typer.Exit: With code 2 when zero or more than one trigger flag was
            given; with code 1 when ``--run-at`` is not a timezone-aware ISO
            8601 instant.
    """
    given: int = sum(flag is not None for flag in (cron, interval_seconds, run_at))
    if given != 1:
        typer.secho(
            "Exactly one of --cron, --interval-seconds or --run-at is required",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    parsed_run_at: Optional[datetime] = None
    if run_at is not None:
        try:
            parsed_run_at = datetime.fromisoformat(run_at)
        except ValueError:
            typer.secho(f"Invalid --run-at: {run_at}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        if parsed_run_at.tzinfo is None:
            typer.secho(
                f"--run-at must be timezone-aware, got: {run_at}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
    try:
        if cron is not None:
            return CronTriggerDAO(expression=cron, tz=tz)
        if interval_seconds is not None:
            return IntervalTriggerDAO(every_seconds=interval_seconds)
        return OneShotTriggerDAO(run_at=parsed_run_at)  # type: ignore[arg-type]
    except ValidationError as error:
        rejections: list[str] = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
        ]
        typer.secho(f"Invalid schedule: {'; '.join(rejections)}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


def _guard_session_flags(
    *,
    session_mode: SessionMode,
    session_reference: Optional[str],
    coalescing_mode: CoalescingMode,
    coalescing_key: Optional[str],
) -> None:
    """Reject flag combinations that contradict each other.

    Args:
        session_mode (SessionMode): The ``--session-mode`` value.
        session_reference (Optional[str]): The ``--session-reference`` value.
        coalescing_mode (CoalescingMode): The ``--coalescing-mode`` value.
        coalescing_key (Optional[str]): The ``--coalescing-key`` value.

    Raises:
        typer.Exit: With code 2 when a reference is given for a fresh
            schedule or a key for ``none`` coalescing.
    """
    if session_mode == SessionMode.fresh and session_reference is not None:
        typer.secho(
            "--session-reference requires --session-mode continuous",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if session_mode == SessionMode.fresh and coalescing_mode != CoalescingMode.none:
        typer.secho(
            "--coalescing-mode requires --session-mode continuous",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if session_mode == SessionMode.fresh and coalescing_key is not None:
        typer.secho(
            "--coalescing-key requires --session-mode continuous",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    if coalescing_mode == CoalescingMode.none and coalescing_key is not None:
        typer.secho(
            "--coalescing-key requires --coalescing-mode latest_by_key",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)


@schedule_app.command(name="add")
def add_schedule(
    name: str = typer.Option(..., "--name", help="Human-facing schedule name."),
    prompt: str = typer.Option(..., "--prompt", help="Prompt to run on each fire."),
    cron: Optional[str] = typer.Option(None, "--cron", help="Five-field cron expression."),
    interval_seconds: Optional[int] = typer.Option(
        None, "--interval-seconds", help="Interval trigger in seconds."
    ),
    run_at: Optional[str] = typer.Option(
        None, "--run-at", help="Timezone-aware ISO 8601 instant for a one-shot trigger."
    ),
    tz: str = typer.Option("UTC", "--tz", help="IANA timezone for cron triggers."),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Fresh-run working directory override."),
    model: Optional[str] = typer.Option(None, "--model", help="Fresh-run model override."),
    session_mode: SessionMode = typer.Option(
        SessionMode.fresh, "--session-mode", help="fresh or continuous."
    ),
    session_reference: Optional[str] = typer.Option(
        None, "--session-reference", help="Target session id or unique name."
    ),
    coalescing_mode: CoalescingMode = typer.Option(
        CoalescingMode.none, "--coalescing-mode", help="none or latest_by_key."
    ),
    coalescing_key: Optional[str] = typer.Option(
        None, "--coalescing-key", help="Pending-item coalescing key."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the stored schedule as JSON."),
) -> None:
    """Save one new schedule and make sure the shared schedule worker is running and healthy."""
    trigger: TriggerDAO = _build_trigger(
        cron=cron,
        interval_seconds=interval_seconds,
        run_at=run_at,
        tz=tz,
    )
    _guard_session_flags(
        session_mode=session_mode,
        session_reference=session_reference,
        coalescing_mode=coalescing_mode,
        coalescing_key=coalescing_key,
    )
    asyncio.run(
        ScheduleDispatch.add(
            name=name,
            prompt=prompt,
            trigger=trigger,
            session_mode=session_mode,
            session_reference=session_reference,
            coalescing_mode=coalescing_mode,
            coalescing_key=coalescing_key,
            cwd=cwd,
            model=model,
            as_json=as_json,
        )
    )


@schedule_app.command(name="edit")
def edit_schedule(
    schedule: str = typer.Option(..., "--schedule", help="Schedule id or name to replace."),
    name: str = typer.Option(..., "--name", help="New human-facing schedule name."),
    prompt: str = typer.Option(..., "--prompt", help="New prompt to run on each fire."),
    cron: Optional[str] = typer.Option(None, "--cron", help="Five-field cron expression."),
    interval_seconds: Optional[int] = typer.Option(
        None, "--interval-seconds", help="Interval trigger in seconds."
    ),
    run_at: Optional[str] = typer.Option(
        None, "--run-at", help="Timezone-aware ISO 8601 instant for a one-shot trigger."
    ),
    tz: str = typer.Option("UTC", "--tz", help="IANA timezone for cron triggers."),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Fresh-run working directory override."),
    model: Optional[str] = typer.Option(None, "--model", help="Fresh-run model override."),
    session_mode: SessionMode = typer.Option(
        SessionMode.fresh, "--session-mode", help="fresh or continuous."
    ),
    session_reference: Optional[str] = typer.Option(
        None, "--session-reference", help="Target session id or unique name."
    ),
    coalescing_mode: CoalescingMode = typer.Option(
        CoalescingMode.none, "--coalescing-mode", help="none or latest_by_key."
    ),
    coalescing_key: Optional[str] = typer.Option(
        None, "--coalescing-key", help="Pending-item coalescing key."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the updated schedule as JSON."),
) -> None:
    """Replace one schedule's whole definition."""
    trigger: TriggerDAO = _build_trigger(
        cron=cron,
        interval_seconds=interval_seconds,
        run_at=run_at,
        tz=tz,
    )
    _guard_session_flags(
        session_mode=session_mode,
        session_reference=session_reference,
        coalescing_mode=coalescing_mode,
        coalescing_key=coalescing_key,
    )
    asyncio.run(
        ScheduleDispatch.edit(
            schedule=schedule,
            name=name,
            prompt=prompt,
            trigger=trigger,
            session_mode=session_mode,
            session_reference=session_reference,
            coalescing_mode=coalescing_mode,
            coalescing_key=coalescing_key,
            cwd=cwd,
            model=model,
            as_json=as_json,
        )
    )


@schedule_app.command(name="show")
def show_schedule(
    schedule: str = typer.Option(..., "--schedule", help="Schedule id or name."),
    as_json: bool = typer.Option(False, "--json", help="Print the schedule as JSON."),
) -> None:
    """Print one schedule's definition and next due."""
    asyncio.run(ScheduleDispatch.show(schedule=schedule, as_json=as_json))


@schedule_app.command(name="list")
def list_schedules(
    disabled: bool = typer.Option(False, "--disabled", help="List disabled schedules."),
    as_json: bool = typer.Option(False, "--json", help="Print the summaries as JSON."),
) -> None:
    """Print the schedule table."""
    asyncio.run(ScheduleDispatch.list(disabled=disabled, as_json=as_json))


@schedule_app.command(name="start")
def start_schedule(
    schedule: str = typer.Option(..., "--schedule", help="Schedule id or name."),
    as_json: bool = typer.Option(False, "--json", help="Print the schedule as JSON."),
) -> None:
    """Enable one schedule and make sure the shared schedule worker is running and healthy."""
    asyncio.run(ScheduleDispatch.start(schedule=schedule, as_json=as_json))


@schedule_app.command(name="stop")
def stop_schedule(
    schedule: str = typer.Option(..., "--schedule", help="Schedule id or name."),
    as_json: bool = typer.Option(False, "--json", help="Print the schedule as JSON."),
) -> None:
    """Disable one enabled schedule."""
    asyncio.run(ScheduleDispatch.stop(schedule=schedule, as_json=as_json))


@schedule_app.command(name="status")
def schedule_status(
    schedule: Optional[str] = typer.Option(None, "--schedule", help="Schedule id or name to include."),
    as_json: bool = typer.Option(False, "--json", help="Print the status as JSON."),
) -> None:
    """Show whether the shared schedule worker is healthy and when work is next due (read-only)."""
    asyncio.run(ScheduleDispatch.status(schedule=schedule, as_json=as_json))


@schedule_app.command(name="trigger")
def trigger_schedule(
    schedule: str = typer.Option(..., "--schedule", help="Schedule id or name."),
) -> None:
    """Queue one manual invocation for one schedule, due now."""
    asyncio.run(ScheduleDispatch.trigger(schedule=schedule))


@schedule_app.command(name="report")
def report_schedule(
    schedule: str = typer.Option(..., "--schedule", help="Schedule id or name."),
    days: int = typer.Option(30, "--days", help="Window length in days (1 to 90)."),
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
) -> None:
    """Print one schedule's window report."""
    asyncio.run(ScheduleDispatch.report(schedule=schedule, days=days, as_json=as_json))


@schedule_app.command(name="worker")
def run_schedule_worker(
    run_timeout_seconds: int = typer.Option(
        3600,
        "--run-timeout-seconds",
        help="Running invocations older than this are failed at worker start (D24).",
    ),
    earlier_workers_stopped: bool = typer.Option(
        False,
        "--earlier-workers-stopped",
        help="Confirm every worker of an earlier development build has stopped (one-time upgrade).",
    ),
    launch_id: Optional[str] = typer.Option(
        None, "--launch-id", hidden=True, help="Generation id issued by the automatic worker start."
    ),
) -> None:
    """Run the shared schedule worker in the foreground (administration and debugging only)."""
    ScheduleDispatch.worker(
        run_timeout_seconds=run_timeout_seconds,
        earlier_workers_stopped=earlier_workers_stopped,
        launch_id=launch_id,
    )


@schedule_app.command(name="delete")
def delete_schedule(
    schedule: str = typer.Option(..., "--schedule", help="Schedule id or name."),
    yes: bool = typer.Option(False, "--yes", help="Confirm the deletion."),
    as_json: bool = typer.Option(False, "--json", help="Print the schedule as JSON."),
) -> None:
    """Soft-delete one active schedule."""
    if not yes:
        typer.secho("--yes is required to delete a schedule", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    asyncio.run(ScheduleDispatch.delete(schedule=schedule, as_json=as_json))
