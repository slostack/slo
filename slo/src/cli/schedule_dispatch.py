"""`ScheduleDispatch` — parsed CLI flags → service calls → printed output and exit code."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal, Optional, cast

import typer
from pydantic import ValidationError

from src.schedules.dao import (
    CronTriggerDAO,
    IntervalTriggerDAO,
    NewScheduleDAO,
    OneShotTriggerDAO,
    ScheduleDAO,
    ScheduleInvocationDAO,
    ScheduleReportDAO,
    ScheduleStateFilter,
    ScheduleSummaryDAO,
    TriggerDAO,
)
from src.schedules.database import ScheduleDatabase, default_database_path
from src.schedules.exceptions import (
    ScheduleInvalidError,
    ScheduleNameTakenError,
    ScheduleNotFoundError,
)
from src.schedules.invocation_repository import ScheduleInvocationRepository
from src.schedules.operational_app_service import (
    CreateOperationalScheduleAppService,
    OperationalScheduleDAO,
    ScheduleNotOperationalError,
    ScheduleStatusAppService,
    ScheduleStatusDAO,
    StartOperationalScheduleAppService,
)
from src.schedules.rendering import ScheduleTableRenderer, trigger_summary
from src.schedules.repository import ScheduleRepository
from src.schedules.service import ScheduleService
from src.schedules.worker_runtime import (
    ScheduleWorkerHealthDAO,
    ScheduleWorkerLocationDAO,
    ScheduleWorkerRuntime,
)

__all__ = ["CoalescingMode", "ScheduleDispatch", "SessionMode"]

_EXIT_INVALID: int = 1


class SessionMode(str, Enum):
    """The ``--session-mode`` flag choices."""

    fresh = "fresh"
    continuous = "continuous"


class CoalescingMode(str, Enum):
    """The ``--coalescing-mode`` flag choices."""

    none = "none"
    latest_by_key = "latest_by_key"


def _validation_diagnostic(*, error: ValidationError) -> str:
    """Render a Pydantic validation error without echoing the rejected input values.

    Args:
        error (ValidationError): The validation failure to sanitise.

    Returns:
        str: One ``location: message`` line per rejection; prompt text never appears.
    """
    parts: list[str] = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    ]
    return "; ".join(parts)


class ScheduleDispatch:
    """Maps one command's flags onto `ScheduleService` and prints the result."""

    @classmethod
    def _build_service(cls) -> ScheduleService:
        """Build the service on the default database path.

        Returns:
            ScheduleService: A service wired to ``SLO_SCHEDULES_DIR`` or
                ``$SLO_HOME/schedules``.
        """
        return ScheduleService(
            database=ScheduleDatabase(db_path=default_database_path()),
            schedules=ScheduleRepository(),
            invocations=ScheduleInvocationRepository(),
            session_history=None,
        )

    @classmethod
    def _build_runtime(cls) -> ScheduleWorkerRuntime:
        """Build the shared worker runtime on the configured stores.

        Returns:
            ScheduleWorkerRuntime: The runtime for ``SLO_SCHEDULES_DIR`` / ``SLO_HOME``.
        """
        return ScheduleWorkerRuntime(location=ScheduleWorkerLocationDAO.at_default_paths())

    @classmethod
    def _now(cls) -> datetime:
        """Return the current UTC instant (the boundary clock).

        Returns:
            datetime: The timezone-aware UTC now.
        """
        return datetime.now(timezone.utc)

    @classmethod
    def _build_definition(
        cls,
        *,
        name: str,
        prompt: str,
        trigger: TriggerDAO,
        session_mode: SessionMode,
        session_reference: Optional[str],
        coalescing_mode: CoalescingMode,
        coalescing_key: Optional[str],
        cwd: Optional[str],
        model: Optional[str],
    ) -> NewScheduleDAO:
        """Build the validated definition from one command's flags.

        Args:
            name (str): The ``--name`` value.
            prompt (str): The ``--prompt`` value.
            trigger (TriggerDAO): The built trigger DAO.
            session_mode (SessionMode): The ``--session-mode`` value.
            session_reference (Optional[str]): The ``--session-reference`` value.
            coalescing_mode (CoalescingMode): The ``--coalescing-mode`` value.
            coalescing_key (Optional[str]): The ``--coalescing-key`` value.
            cwd (Optional[str]): The ``--cwd`` value.
            model (Optional[str]): The ``--model`` value.

        Returns:
            NewScheduleDAO: The validated definition.
        """
        return NewScheduleDAO(
            name=name,
            prompt=prompt,
            trigger=trigger,
            session_mode=cast(Literal["fresh", "continuous"], session_mode.value),
            session_reference=session_reference,
            coalescing_mode=cast(Literal["none", "latest_by_key"], coalescing_mode.value),
            coalescing_key=coalescing_key,
            cwd=cwd,
            model=model,
        )

    @classmethod
    def _print_schedule(cls, *, schedule: ScheduleDAO, as_json: bool) -> None:
        """Print one schedule as JSON or as the text detail.

        Args:
            schedule (ScheduleDAO): The stored row to print.
            as_json (bool): ``--json`` was given.
        """
        if as_json:
            typer.echo(schedule.model_dump_json())
            return
        typer.echo(schedule.id)
        typer.echo(f"Name: {schedule.name}")
        typer.echo(f"Trigger: {trigger_summary(trigger=schedule.trigger)}")
        typer.echo(f"Next Due: {schedule.next_due_at.isoformat() if schedule.next_due_at else '-'}")
        typer.echo(f"Mode: {schedule.session_mode}")
        typer.echo(f"Target Session: {schedule.session_reference or '-'}")

    @classmethod
    def _worker_line(cls, *, worker: ScheduleWorkerHealthDAO) -> str:
        """Render one worker observation as a single text line.

        Args:
            worker (ScheduleWorkerHealthDAO): The observation.

        Returns:
            str: ``Worker: <state> ...`` with the pid, last tick or reason.
        """
        details: list[str] = []
        if worker.pid is not None:
            details.append(f"pid {worker.pid}")
        if worker.last_tick_at is not None:
            details.append(f"last tick {worker.last_tick_at.isoformat()}")
        suffix: str = f" ({', '.join(details)})" if details else ""
        reason: str = f" - {worker.reason}" if worker.reason and not worker.is_healthy else ""
        return f"Worker: {worker.state}{suffix}{reason}"

    @classmethod
    def _print_operational(cls, *, operational: OperationalScheduleDAO, as_json: bool) -> None:
        """Print a saved schedule whose healthy worker will fire it.

        The JSON object keeps every schedule field and adds ``operational``
        and ``worker``.

        Args:
            operational (OperationalScheduleDAO): The schedule and its worker.
            as_json (bool): ``--json`` was given.
        """
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        **operational.schedule.model_dump(mode="json"),
                        "operational": True,
                        "worker": operational.worker.model_dump(mode="json"),
                    }
                )
            )
            return
        cls._print_schedule(schedule=operational.schedule, as_json=False)
        typer.echo(cls._worker_line(worker=operational.worker))

    @classmethod
    def _fail_not_operational(cls, *, error: ScheduleNotOperationalError, as_json: bool) -> None:
        """Report a saved schedule without a healthy worker and stop with exit 1.

        Both forms carry the saved id and the cause; stderr always says
        ``schedule saved, but not operational`` with the recovery command.

        Args:
            error (ScheduleNotOperationalError): The partial success.
            as_json (bool): ``--json`` was given.

        Raises:
            typer.Exit: Always, with code 1.
        """
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        **error.schedule.model_dump(mode="json"),
                        "operational": False,
                        "worker": error.health.model_dump(mode="json"),
                        "error": str(error),
                    }
                )
            )
        else:
            cls._print_schedule(schedule=error.schedule, as_json=False)
            typer.echo(cls._worker_line(worker=error.health))
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        typer.secho(
            f"Saved schedule id: {error.schedule.id}. Fix the cause, then run "
            f"`slo schedule start --schedule {error.schedule.id}` (do not add it again).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=_EXIT_INVALID) from error

    @classmethod
    def _fail(cls, *, error: Exception) -> None:
        """Print one domain rejection and stop with exit code 1.

        Args:
            error (Exception): The domain error to report.
        """
        if isinstance(error, ValidationError):
            message: str = f"Invalid schedule: {_validation_diagnostic(error=error)}"
        else:
            message = str(error)
        typer.secho(message, fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_EXIT_INVALID) from error

    @classmethod
    async def add(
        cls,
        *,
        name: str,
        prompt: str,
        trigger: TriggerDAO,
        session_mode: SessionMode,
        session_reference: Optional[str],
        coalescing_mode: CoalescingMode,
        coalescing_key: Optional[str],
        cwd: Optional[str],
        model: Optional[str],
        as_json: bool,
    ) -> None:
        """Run one add and print the stored schedule.

        Args:
            name (str): The ``--name`` value.
            prompt (str): The ``--prompt`` value.
            trigger (TriggerDAO): The built trigger DAO.
            session_mode (SessionMode): The ``--session-mode`` value.
            session_reference (Optional[str]): The ``--session-reference`` value.
            coalescing_mode (CoalescingMode): The ``--coalescing-mode`` value.
            coalescing_key (Optional[str]): The ``--coalescing-key`` value.
            cwd (Optional[str]): The ``--cwd`` value.
            model (Optional[str]): The ``--model`` value.
            as_json (bool): ``--json`` was given.
        """
        service: ScheduleService = cls._build_service()
        try:
            new_schedule: NewScheduleDAO = cls._build_definition(
                name=name,
                prompt=prompt,
                trigger=trigger,
                session_mode=session_mode,
                session_reference=session_reference,
                coalescing_mode=coalescing_mode,
                coalescing_key=coalescing_key,
                cwd=cwd,
                model=model,
            )
            operational: OperationalScheduleDAO = await CreateOperationalScheduleAppService(
                schedules=service, runtime=cls._build_runtime(), new_schedule=new_schedule, now=cls._now()
            ).invoke()
        except ScheduleNotOperationalError as error:
            cls._fail_not_operational(error=error, as_json=as_json)
            return
        except (ScheduleInvalidError, ScheduleNameTakenError, ValidationError) as error:
            cls._fail(error=error)
            return
        finally:
            await service.close()
        cls._print_operational(operational=operational, as_json=as_json)

    @classmethod
    async def edit(
        cls,
        *,
        schedule: str,
        name: str,
        prompt: str,
        trigger: TriggerDAO,
        session_mode: SessionMode,
        session_reference: Optional[str],
        coalescing_mode: CoalescingMode,
        coalescing_key: Optional[str],
        cwd: Optional[str],
        model: Optional[str],
        as_json: bool,
    ) -> None:
        """Run one edit and print the updated schedule.

        Args:
            schedule (str): The ``--schedule`` reference.
            name (str): The ``--name`` value.
            prompt (str): The ``--prompt`` value.
            trigger (TriggerDAO): The built trigger DAO.
            session_mode (SessionMode): The ``--session-mode`` value.
            session_reference (Optional[str]): The ``--session-reference`` value.
            coalescing_mode (CoalescingMode): The ``--coalescing-mode`` value.
            coalescing_key (Optional[str]): The ``--coalescing-key`` value.
            cwd (Optional[str]): The ``--cwd`` value.
            model (Optional[str]): The ``--model`` value.
            as_json (bool): ``--json`` was given.
        """
        service: ScheduleService = cls._build_service()
        try:
            changes: NewScheduleDAO = cls._build_definition(
                name=name,
                prompt=prompt,
                trigger=trigger,
                session_mode=session_mode,
                session_reference=session_reference,
                coalescing_mode=coalescing_mode,
                coalescing_key=coalescing_key,
                cwd=cwd,
                model=model,
            )
            edited_schedule = await service.edit(reference=schedule, changes=changes, now=cls._now())
        except (
            ScheduleInvalidError,
            ScheduleNameTakenError,
            ScheduleNotFoundError,
            ValidationError,
        ) as error:
            cls._fail(error=error)
            return
        finally:
            await service.close()
        cls._print_schedule(schedule=edited_schedule, as_json=as_json)

    @classmethod
    async def show(cls, *, schedule: str, as_json: bool) -> None:
        """Run one show and print the stored schedule.

        Args:
            schedule (str): The ``--schedule`` reference.
            as_json (bool): ``--json`` was given.
        """
        service: ScheduleService = cls._build_service()
        try:
            found_schedule = await service.show(reference=schedule)
        except ScheduleNotFoundError as error:
            cls._fail(error=error)
            return
        finally:
            await service.close()
        cls._print_schedule(schedule=found_schedule, as_json=as_json)

    @classmethod
    async def list(cls, *, disabled: bool, as_json: bool) -> None:
        """Run one list and print the renderer table or JSON.

        Args:
            disabled (bool): ``--disabled`` was given.
            as_json (bool): ``--json`` was given.
        """
        state: ScheduleStateFilter = "disabled" if disabled else "active"
        service: ScheduleService = cls._build_service()
        summaries: list[ScheduleSummaryDAO] = await service.list_by_state(state=state)
        await service.close()
        if as_json:
            typer.echo(json.dumps([summary.model_dump(mode="json") for summary in summaries]))
            return
        typer.echo(ScheduleTableRenderer.render(schedules=summaries, state=state))

    @classmethod
    async def start(cls, *, schedule: str, as_json: bool) -> None:
        """Enable one schedule, make scheduling operational and print both.

        Args:
            schedule (str): The ``--schedule`` reference.
            as_json (bool): ``--json`` was given.
        """
        service: ScheduleService = cls._build_service()
        try:
            operational: OperationalScheduleDAO = await StartOperationalScheduleAppService(
                schedules=service, runtime=cls._build_runtime(), reference=schedule, now=cls._now()
            ).invoke()
        except ScheduleNotOperationalError as error:
            cls._fail_not_operational(error=error, as_json=as_json)
            return
        except (ScheduleNotFoundError, ScheduleInvalidError) as error:
            cls._fail(error=error)
            return
        finally:
            await service.close()
        cls._print_operational(operational=operational, as_json=as_json)

    @classmethod
    async def status(cls, *, schedule: Optional[str], as_json: bool) -> None:
        """Print the shared worker's health and the next due time; read-only.

        Args:
            schedule (Optional[str]): The ``--schedule`` reference, if given.
            as_json (bool): ``--json`` was given.

        Raises:
            typer.Exit: With code 1 when the worker is not healthy or the
                schedule is not found.
        """
        service: ScheduleService = cls._build_service()
        runtime: ScheduleWorkerRuntime = cls._build_runtime()
        try:
            status: ScheduleStatusDAO = await ScheduleStatusAppService(
                schedules=service, runtime=runtime, db_path=runtime.location.db_path, reference=schedule
            ).invoke()
        except ScheduleNotFoundError as error:
            cls._fail(error=error)
            return
        finally:
            await service.close()
        cls._print_status(status=status, as_json=as_json)
        if not status.worker.is_healthy:
            raise typer.Exit(code=_EXIT_INVALID)

    @classmethod
    def _print_status(cls, *, status: ScheduleStatusDAO, as_json: bool) -> None:
        """Print one status as JSON or text.

        Args:
            status (ScheduleStatusDAO): The observation.
            as_json (bool): ``--json`` was given.
        """
        if as_json:
            typer.echo(status.model_dump_json())
            return
        typer.echo(cls._worker_line(worker=status.worker))
        if status.schedule is not None:
            typer.echo(f"Schedule: {status.schedule.id} ({status.schedule.name})")
            typer.echo(f"Enabled: {'yes' if status.schedule.enabled else 'no'}")
        typer.echo(f"Next Due: {status.next_due_at.isoformat() if status.next_due_at else '-'}")

    @classmethod
    async def stop(cls, *, schedule: str, as_json: bool) -> None:
        """Run one stop and print the stored schedule.

        Args:
            schedule (str): The ``--schedule`` reference.
            as_json (bool): ``--json`` was given.
        """
        await cls._lifecycle(schedule=schedule, verb="stop", as_json=as_json)

    @classmethod
    def worker(
        cls, *, run_timeout_seconds: int, earlier_workers_stopped: bool, launch_id: Optional[str]
    ) -> None:
        """Run the schedule worker until SIGTERM (foreground, or detached by the runtime).

        Args:
            run_timeout_seconds (int): Running invocations older than this are
                failed at worker start (D24).
            earlier_workers_stopped (bool): ``--earlier-workers-stopped`` was
                given: the operator confirmed every earlier-layout worker stopped.
            launch_id (Optional[str]): The generation id of a runtime-started
                detached worker; None for a manual foreground worker.

        Raises:
            typer.Exit: With code 1 when the worker cannot start.
        """
        from src.schedules.worker import ScheduleWorker
        from src.schedules.exceptions import ScheduleWorkerStartError

        location: ScheduleWorkerLocationDAO = ScheduleWorkerLocationDAO.at_default_paths()
        worker: ScheduleWorker = ScheduleWorker(
            db_path=location.db_path,
            channel_db_path=location.channel_db_path,
            run_timeout_seconds=run_timeout_seconds,
            earlier_workers_stopped=earlier_workers_stopped,
            location=location,
            launch_id=launch_id,
        )
        try:
            worker.run_foreground()
        except ScheduleWorkerStartError as error:
            typer.secho(str(error), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from error

    @classmethod
    async def trigger(cls, *, schedule: str) -> None:
        """Queue one manual invocation and print its id.

        Args:
            schedule (str): The ``--schedule`` reference.
        """
        service: ScheduleService = cls._build_service()
        try:
            invocation: ScheduleInvocationDAO = await service.trigger_now(reference=schedule, now=cls._now())
        except (ScheduleNotFoundError, ScheduleInvalidError) as error:
            cls._fail(error=error)
            return
        finally:
            await service.close()
        typer.echo(str(invocation.id))

    @classmethod
    async def report(cls, *, schedule: str, days: int, as_json: bool) -> None:
        """Print one schedule's window report.

        Args:
            schedule (str): The ``--schedule`` reference.
            days (int): The window length in days, 1 to 90.
            as_json (bool): ``--json`` was given.

        Raises:
            typer.Exit: With code 2 when ``days`` is outside 1 to 90; with code 1
                when the schedule is not found.
        """
        from src.schedules.report import ScheduleReportService

        if not 1 <= days <= 90:
            typer.secho("--days must be between 1 and 90", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        database: ScheduleDatabase = ScheduleDatabase(db_path=default_database_path())
        now: datetime = cls._now()
        window_end: datetime = now
        window_start: datetime = now - timedelta(days=days)
        report_service: ScheduleReportService = ScheduleReportService(
            database=database,
            schedules=ScheduleRepository(),
            invocations=ScheduleInvocationRepository(),
        )
        try:
            report: ScheduleReportDAO = await report_service.build(
                reference=schedule,
                window_start=window_start,
                window_end=window_end,
            )
        except ScheduleNotFoundError as error:
            typer.secho(str(error), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from error
        finally:
            await database.close()
        if as_json:
            typer.echo(report.model_dump_json())
            return
        typer.echo(
            f"{report.name} | {report.window_start:%Y-%m-%d %H:%M} to {report.window_end:%Y-%m-%d %H:%M} UTC"
        )
        typer.echo(
            f"total={report.counts.total} pending={report.counts.pending}"
            f" delivered={report.counts.delivered} skipped={report.counts.skipped}"
            f" failed={report.counts.failed}"
        )
        typer.echo(
            f"accepted={report.counts.accepted} cancelled={report.counts.cancelled}"
            f" superseded={report.counts.superseded} replied={report.counts.replied}"
        )
        typer.echo(
            f"pending_outcome={report.counts.pending_outcome}"
            f" outcome_unavailable={report.counts.outcome_unavailable}"
        )
        typer.echo(
            f"running={report.counts.running} completed={report.counts.completed}"
            f" run_failed={report.counts.run_failed}"
        )
        recent_invocation: ScheduleInvocationDAO
        for recent_invocation in report.recent_invocations:
            reason: str = (
                recent_invocation.failure_reason
                or recent_invocation.skip_reason
                or recent_invocation.cancel_reason
                or ""
            )
            typer.echo(f"{recent_invocation.due_at:%Y-%m-%d %H:%M} {recent_invocation.status} {reason}")

    @classmethod
    async def delete(cls, *, schedule: str, as_json: bool) -> None:
        """Run one delete and print the stored schedule.

        Args:
            schedule (str): The ``--schedule`` reference.
            as_json (bool): ``--json`` was given.
        """
        await cls._lifecycle(schedule=schedule, verb="delete", as_json=as_json)

    @classmethod
    async def _lifecycle(
        cls,
        *,
        schedule: str,
        verb: Literal["stop", "delete"],
        as_json: bool,
    ) -> None:
        """Run one lifecycle verb and print the stored schedule.

        Args:
            schedule (str): The ``--schedule`` reference.
            verb (Literal["start", "stop", "delete"]): The lifecycle verb.
            as_json (bool): ``--json`` was given.
        """
        service: ScheduleService = cls._build_service()
        stored_schedule: ScheduleDAO
        try:
            if verb == "start":
                stored_schedule = await service.start(reference=schedule, now=cls._now())
            elif verb == "stop":
                stored_schedule = await service.stop(reference=schedule, now=cls._now())
            else:
                stored_schedule = await service.delete(reference=schedule, now=cls._now())
        except (ScheduleNotFoundError, ScheduleInvalidError) as error:
            cls._fail(error=error)
            return
        finally:
            await service.close()
        cls._print_schedule(schedule=stored_schedule, as_json=as_json)
