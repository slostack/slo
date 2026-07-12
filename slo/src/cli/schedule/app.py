"""Typer sub-app for scheduled tasks."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

import typer

from config.cfg import cfg as _cfg
from src.agents.slo_agent.history.inbox.lease import SessionOwnershipLeaseStore
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.scheduling.dao import (
    CalendarTriggerDAO,
    CronTriggerDAO,
    IntervalTriggerDAO,
    LoadedScheduleDAO,
    OneShotTriggerDAO,
    ScheduleDefinitionDAO,
    ScheduleRunRecordDAO,
    ScheduleSessionPolicyDAO,
    TriggerDAO,
)
from src.scheduling.os.integration import ScheduleOSIntegration
from src.scheduling.runtime.cleanup import ScheduleCleanupService
from src.scheduling.runtime.executor import ScheduleExecutor
from src.scheduling.store import ScheduleStore

__all__ = ["schedule_app"]


schedule_app: typer.Typer = typer.Typer(
    name="schedule",
    help="Manage scheduled Slo tasks.",
    add_completion=False,
)


@schedule_app.command(name="add")
def add_schedule(
    name: str = typer.Option(..., "--name", help="Human-facing schedule name."),
    prompt: str = typer.Option(..., "--prompt", help="Prompt to run on each fire."),
    cron: Optional[str] = typer.Option(None, "--cron", help="Five-field cron expression."),
    interval_seconds: Optional[int] = typer.Option(
        None, "--interval-seconds", help="Interval trigger in seconds."
    ),
    run_at: Optional[str] = typer.Option(None, "--run-at", help="ISO8601 timestamp for a one-shot trigger."),
    tz: str = typer.Option("UTC", "--tz", help="IANA timezone for cron/calendar triggers."),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Working directory override."),
    model: Optional[str] = typer.Option(None, "--model", help="Model override."),
    session_mode: str = typer.Option("fresh", "--session-mode", help="fresh or continuous."),
    session_reference: Optional[str] = typer.Option(
        None, "--session-reference", help="Target session id or unique name."
    ),
    coalescing_mode: str = typer.Option("none", "--coalescing-mode", help="none or latest_by_key."),
    coalescing_key: Optional[str] = typer.Option(
        None, "--coalescing-key", help="Pending-item coalescing key."
    ),
) -> None:
    """Persist one new schedule definition."""
    definition: ScheduleDefinitionDAO = _build_definition(
        name=name,
        prompt=prompt,
        cron=cron,
        interval_seconds=interval_seconds,
        run_at=run_at,
        tz=tz,
        cwd=cwd,
        model=model,
        session_mode=session_mode,
        session_reference=session_reference,
        coalescing_mode=coalescing_mode,
        coalescing_key=coalescing_key,
    )
    ScheduleStore.create(definition=definition, initial_next_run_at=None)
    typer.echo(definition.schedule_id)
    typer.echo(f"Mode: {definition.session_mode}")
    typer.echo(
        "Target Session: "
        + (
            definition.session_policy.session_reference
            if definition.session_policy is not None
            and definition.session_policy.session_reference is not None
            else ("schedule-owned" if definition.session_mode == "continuous" else "-")
        )
    )


@schedule_app.command(name="edit")
def edit_schedule(
    name: str = typer.Option(..., "--name", help="Schedule id or normalized name."),
    schedule_name: str = typer.Option(..., "--schedule-name", help="Human-facing schedule name."),
    prompt: str = typer.Option(..., "--prompt", help="Prompt to run on each fire."),
    cron: Optional[str] = typer.Option(None, "--cron", help="Five-field cron expression."),
    interval_seconds: Optional[int] = typer.Option(
        None, "--interval-seconds", help="Interval trigger in seconds."
    ),
    run_at: Optional[str] = typer.Option(None, "--run-at", help="ISO8601 timestamp for a one-shot trigger."),
    tz: str = typer.Option("UTC", "--tz", help="IANA timezone for cron/calendar triggers."),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Working directory override."),
    model: Optional[str] = typer.Option(None, "--model", help="Model override."),
    session_mode: str = typer.Option("fresh", "--session-mode", help="fresh or continuous."),
    session_reference: Optional[str] = typer.Option(
        None, "--session-reference", help="Target session id or unique name."
    ),
    coalescing_mode: str = typer.Option("none", "--coalescing-mode", help="none or latest_by_key."),
    coalescing_key: Optional[str] = typer.Option(
        None, "--coalescing-key", help="Pending-item coalescing key."
    ),
) -> None:
    """Rewrite one persisted schedule definition."""
    loaded = ScheduleStore.load(reference=name)
    definition: ScheduleDefinitionDAO = _build_definition(
        name=schedule_name,
        prompt=prompt,
        cron=cron,
        interval_seconds=interval_seconds,
        run_at=run_at,
        tz=tz,
        cwd=cwd,
        model=model,
        session_mode=session_mode,
        session_reference=session_reference,
        coalescing_mode=coalescing_mode,
        coalescing_key=coalescing_key,
        schedule_id=loaded.schedule_id,
    )
    ScheduleStore.update_definition(schedule_id=loaded.schedule_id, definition=definition)
    typer.echo(loaded.schedule_id)
    typer.echo(f"Mode: {definition.session_mode}")
    typer.echo(f"Target Session: {_target_summary(definition=definition)}")


@schedule_app.command(name="list")
def list_schedules() -> None:
    """List persisted schedules with delivery metadata."""
    typer.echo("Name | Mode | Trigger | Target Session | Installed | Last Delivery")
    for loaded in ScheduleStore.load_all():
        typer.echo(
            " | ".join(
                [
                    loaded.definition.name,
                    loaded.definition.session_mode,
                    _trigger_summary(trigger=loaded.definition.trigger),
                    _target_summary(definition=loaded.definition),
                    _installed_summary(loaded=loaded),
                    _last_delivery_summary(loaded=loaded),
                ]
            )
        )


@schedule_app.command(name="show")
def show_schedule(name: str = typer.Option(..., "--name", help="Schedule id or normalized name.")) -> None:
    """Show one schedule definition and state."""
    loaded = ScheduleStore.load(reference=name)
    typer.echo(f"Name: {loaded.definition.name}")
    typer.echo(f"Mode: {loaded.definition.session_mode}")
    typer.echo(f"Target Session: {_target_summary(definition=loaded.definition)}")
    typer.echo(f"Last Delivery: {_last_delivery_summary(loaded=loaded)}")


@schedule_app.command(name="execute")
def execute_schedule(name: str = typer.Option(..., "--name", help="Schedule id or normalized name.")) -> None:
    """Execute one due schedule fire immediately."""
    _run_schedule_execution(reference=name)


@schedule_app.command(name="run")
def run_schedule(name: str = typer.Option(..., "--name", help="Schedule id or normalized name.")) -> None:
    """Alias for `schedule execute`."""
    _run_schedule_execution(reference=name)


@schedule_app.command(name="install")
def install_schedule(name: str = typer.Option(..., "--name", help="Schedule id or normalized name.")) -> None:
    """Install one schedule into the local OS scheduler."""
    status = ScheduleOSIntegration().install(reference=name)
    typer.echo(f"Installed: {status.installed}")


@schedule_app.command(name="uninstall")
def uninstall_schedule(
    name: str = typer.Option(..., "--name", help="Schedule id or normalized name.")
) -> None:
    """Uninstall one schedule from the local OS scheduler."""
    status = ScheduleOSIntegration().uninstall(reference=name)
    typer.echo(f"Installed: {status.installed}")


@schedule_app.command(name="reports")
def list_reports(name: str = typer.Option(..., "--name", help="Schedule id or normalized name.")) -> None:
    """List run records for one schedule."""
    loaded = ScheduleStore.load(reference=name)
    for record in _load_run_records(schedule_id=loaded.schedule_id):
        typer.echo(f"{record.run_id} | {record.delivery_path} | {record.delivery_state}")


@schedule_app.command(name="show-report")
def show_report(
    name: str = typer.Option(..., "--name", help="Schedule id or normalized name."),
    run_id: str = typer.Option(..., "--run-id", help="Run record identifier."),
) -> None:
    """Show one immutable run record."""
    loaded = ScheduleStore.load(reference=name)
    record = _load_run_record(schedule_id=loaded.schedule_id, run_id=run_id)
    typer.echo(f"delivery_path: {record.delivery_path}")
    typer.echo(f"delivery_state: {record.delivery_state}")
    typer.echo(f"session_id: {record.session_id}")
    typer.echo(f"target_session_id: {record.target_session_id}")
    typer.echo(f"coalesced_fire_count: {record.coalesced_fire_count}")


@schedule_app.command(name="cleanup")
def cleanup_schedule(
    name: str = typer.Option(..., "--name", help="Schedule id or normalized name."),
    keep: int = typer.Option(100, "--keep", help="How many newest run records to retain."),
) -> None:
    """Prune old immutable run records."""
    loaded = ScheduleStore.load(reference=name)
    deleted_count: int = ScheduleCleanupService().prune(schedule_id=loaded.schedule_id, keep=keep)
    typer.echo(f"Deleted: {deleted_count}")


def _build_definition(
    *,
    name: str,
    prompt: str,
    cron: Optional[str],
    interval_seconds: Optional[int],
    run_at: Optional[str],
    tz: str,
    cwd: Optional[str],
    model: Optional[str],
    session_mode: str,
    session_reference: Optional[str],
    coalescing_mode: str,
    coalescing_key: Optional[str],
    schedule_id: Optional[str] = None,
) -> ScheduleDefinitionDAO:
    """Build one validated schedule definition from CLI flags."""
    trigger: TriggerDAO = _build_trigger(
        cron=cron,
        interval_seconds=interval_seconds,
        run_at=run_at,
        tz=tz,
    )
    session_policy: Optional[ScheduleSessionPolicyDAO] = _build_session_policy(
        session_mode=session_mode,
        session_reference=session_reference,
        coalescing_mode=coalescing_mode,
        coalescing_key=coalescing_key,
    )
    return ScheduleDefinitionDAO(
        schedule_id=schedule_id or str(uuid4()),
        name=name,
        name_key=ScheduleStore.normalize_name_key(name=name),
        trigger=trigger,
        prompt=prompt,
        cwd=cwd,
        model=model,
        session_mode=session_mode,  # type: ignore[arg-type]
        session_policy=session_policy,
    )


def _build_trigger(
    *,
    cron: Optional[str],
    interval_seconds: Optional[int],
    run_at: Optional[str],
    tz: str,
) -> TriggerDAO:
    """Validate and build exactly one trigger variant."""
    specified_count: int = sum(1 for value in [cron, interval_seconds, run_at] if value is not None)
    if specified_count != 1:
        raise typer.BadParameter(
            "Specify exactly one of --cron, --interval-seconds, or --run-at.",
        )
    if cron is not None:
        return CronTriggerDAO(expression=cron, tz=tz)
    if interval_seconds is not None:
        return IntervalTriggerDAO(every_seconds=interval_seconds)
    assert run_at is not None
    return OneShotTriggerDAO(run_at=datetime.fromisoformat(run_at))


def _build_session_policy(
    *,
    session_mode: str,
    session_reference: Optional[str],
    coalescing_mode: str,
    coalescing_key: Optional[str],
) -> Optional[ScheduleSessionPolicyDAO]:
    """Validate fresh-vs-continuous CLI relationships."""
    if session_mode == "fresh":
        if session_reference is not None or coalescing_mode != "none" or coalescing_key is not None:
            raise typer.BadParameter(
                "Fresh schedules cannot use --session-reference or --coalescing-* flags.",
            )
        return None
    if session_mode != "continuous":
        raise typer.BadParameter("--session-mode must be either fresh or continuous.")
    return ScheduleSessionPolicyDAO(
        session_reference=session_reference,
        coalescing_mode=coalescing_mode,  # type: ignore[arg-type]
        coalescing_key=coalescing_key,
    )


def _trigger_summary(*, trigger: TriggerDAO) -> str:
    """Return a one-line trigger summary."""
    if isinstance(trigger, CronTriggerDAO):
        return f"cron:{trigger.expression}"
    if isinstance(trigger, IntervalTriggerDAO):
        return f"interval:{trigger.every_seconds}s"
    if isinstance(trigger, OneShotTriggerDAO):
        return f"one-shot:{trigger.run_at.isoformat()}"
    if isinstance(trigger, CalendarTriggerDAO):
        return f"calendar:{trigger.rrule}"
    return f"unknown:{type(trigger).__name__}"


def _target_summary(*, definition: ScheduleDefinitionDAO) -> str:
    """Return the target-session summary for one definition."""
    if definition.session_mode == "fresh":
        return "-"
    if definition.session_policy is None or definition.session_policy.session_reference is None:
        return "schedule-owned"
    return definition.session_policy.session_reference


def _installed_summary(*, loaded: LoadedScheduleDAO) -> str:
    """Return the install-status summary for one loaded schedule."""
    try:
        status = ScheduleOSIntegration().status(reference=loaded.schedule_id)
    except RuntimeError:
        return "unsupported"
    return "installed" if status.installed else "not-installed"


def _last_delivery_summary(*, loaded: LoadedScheduleDAO) -> str:
    """Return the compact delivery summary for one loaded schedule."""
    if loaded.state.last_delivery_path is None or loaded.state.last_delivery_state is None:
        return "-"
    return f"{loaded.state.last_delivery_path}:{loaded.state.last_delivery_state}"


def _load_run_records(*, schedule_id: str) -> list[ScheduleRunRecordDAO]:
    """Load all run records for one schedule."""
    runs_dir: Path = ScheduleStore.directory_for(schedule_id=schedule_id) / "runs"
    if not runs_dir.exists():
        return []
    records: list[ScheduleRunRecordDAO] = [
        ScheduleRunRecordDAO.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(runs_dir.glob("*.json"))
    ]
    return sorted(records, key=lambda record: record.started_at)


def _load_run_record(*, schedule_id: str, run_id: str) -> ScheduleRunRecordDAO:
    """Load one immutable run record by id."""
    path: Path = ScheduleStore.directory_for(schedule_id=schedule_id) / "runs" / f"{run_id}.json"
    return ScheduleRunRecordDAO.model_validate_json(path.read_text(encoding="utf-8"))


def _history_root() -> Path:
    """Resolve the canonical session-history root for scheduler delivery state."""
    slo_home: str | None = _cfg("SLO_HOME")
    base_dir: Path = Path(slo_home).expanduser() if slo_home is not None else (Path.home() / ".slo")
    return (base_dir / "sessions" / "history").resolve()


def _build_executor() -> ScheduleExecutor:
    """Build the production schedule executor with canonical session stores."""
    history_root: Path = _history_root()
    return ScheduleExecutor(
        session_lease_store=SessionOwnershipLeaseStore(history_root=history_root),
        session_inbox_store=SessionInboxStore(history_root=history_root),
    )


def _run_schedule_execution(*, reference: str) -> None:
    """Run one schedule fire through the production executor and exit accordingly."""
    exit_code: int = asyncio.run(_build_executor().execute(reference=reference))
    raise typer.Exit(code=exit_code)
