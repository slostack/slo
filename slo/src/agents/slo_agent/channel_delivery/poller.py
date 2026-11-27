"""ChannelPoller — one asyncio task per agent session watching the queue (108.1).

Loop (108.1 §5.3): wait on the local wake event or the poll interval; skip
while busy, paused or the session is not ready; take the first pending
``prompt`` row FIFO; run it through the injected ``TurnRunner``; stamp
``accepted_at`` via the runner's ``on_started`` callback; write the reply;
pause after an aborted run.
"""

from __future__ import annotations

import asyncio
import re
from typing import Optional, TYPE_CHECKING
from uuid import UUID, NAMESPACE_URL, uuid5

from config.logger import log_error, log_warning
from config.timeout_resolver import positive_float_env

from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.note_display import ChannelDisplaySink, ChannelNoteDisplay
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO, TurnRunner
from src.channels.dao import ChannelMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway

if TYPE_CHECKING:
    from src.agents.slo_agent.sessions.service import SloAgentSession

__all__ = ["ChannelDisplaySink", "ChannelPoller", "poll_interval_from_env", "workflow_id_from_note"]

_DEFAULT_POLL_INTERVAL_SECONDS: float = 0.5
_HEARTBEAT_INTERVAL_SECONDS: float = 5.0

_WORKFLOW_ID_PATTERN: re.Pattern[str] = re.compile(r"\[workflow ([^\]\s]+)\]")


def workflow_id_from_note(*, text: str) -> str:
    """Return the workflow id embedded in a note's ``[workflow X]`` prefix.

    The notifier writes every workflow note with a leading ``[workflow <id>]
    marker; channel rows carry no payload column, so the receiving side reads
    the id from the text. Unknown shapes fall back to ``wf-unknown``.

    Args:
        text (str): Note contents.

    Returns:
        str: The parsed workflow id, or ``wf-unknown``.
    """
    match: Optional[re.Match[str]] = _WORKFLOW_ID_PATTERN.search(text)
    return match.group(1) if match is not None else "wf-unknown"


def poll_interval_from_env() -> float:
    """Return the configured poll interval in seconds.

    ``SLO_CHANNEL_POLL_MS`` accepts any positive float value in milliseconds;
    invalid values fall back to the 500 ms default.

    Returns:
        float: Poll interval in seconds.
    """
    return (
        positive_float_env(
            primary_name="SLO_CHANNEL_POLL_MS",
            default=_DEFAULT_POLL_INTERVAL_SECONDS * 1000.0,
        )
        / 1000.0
    )


def channel_participant_id_for_session(*, session_id: str) -> UUID:
    """Return the agent participant id for one session id (108.1 §2.3).

    Canonical UUID session ids map to themselves; any other (legacy, named,
    or test) id maps to a deterministic ``uuid5`` so the same session always
    owns the same queue identity.

    Args:
        session_id (str): The session's public id.

    Returns:
        UUID: The participant id used in the queue.
    """
    try:
        return UUID(session_id)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"slo-session:{session_id}")


class ChannelPoller:
    """Polls the queue for one agent session and runs its prompt rows."""

    def __init__(
        self,
        *,
        gateway: ChannelGateway,
        session: "SloAgentSession",
        runner: TurnRunner,
        replies: ReplyWriter,
        boundary_inbox: ChannelBoundaryInbox,
        interval: Optional[float] = None,
        display: Optional[ChannelDisplaySink] = None,
        auto_run: bool = True,
        durable_inbox: bool = False,
        participant_name: Optional[str] = None,
        note_display: Optional[ChannelNoteDisplay] = None,
    ) -> None:
        """Compose the poller around its injected collaborators.

        Args:
            gateway (ChannelGateway): The shared queue API.
            session (SloAgentSession): The session this poller serves; its id
                is the agent participant id.
            runner (TurnRunner): Runs each accepted row (TUI production or
                injected stub).
            replies (ReplyWriter): Answers each finished turn.
            boundary_inbox (ChannelBoundaryInbox): The boundary inbox shared
                with the session's agent; the poller refreshes its forced-row
                snapshot every tick (108.2).
            interval (Optional[float]): Poll interval in seconds; defaults to
                ``SLO_CHANNEL_POLL_MS`` (500 ms).
            display (Optional[ChannelDisplaySink]): Sink for rows shown but
                never run: ``notice`` rows are displayed then accepted;
                ``note`` rows are displayed once per id, and recorded into
                model context when the session is idle (108.3 §5). ``None``
                still settles the rows, without rendering anything.
            auto_run (bool): When ``True`` (default) the poller starts runs
                for pending prompt rows itself; ``False`` (headless workflow
                mode) keeps the boundary inbox and note/notice handling live
                while ``HeadlessRunner`` owns every run (108.3 §5).
            durable_inbox (bool): ``True`` for an interactive session whose
                inbox outlives a closed process (108.3 §6): other agents may
                still send to it while it is closed, and those rows are
                handled when it opens again.
            participant_name (Optional[str]): Display name registered for the
                agent participant; defaults to ``slo <short id>``. Children use
                ``<task_id> (child of <short parent>)`` (108.4 §5).
            note_display (Optional[ChannelNoteDisplay]): The display-once owner
                for notes, shared with ``boundary_inbox`` by the session
                wiring so a note is shown once whichever side meets it first;
                ``None`` gives the poller its own over ``display``.
        """
        self._gateway: ChannelGateway = gateway
        self._session: "SloAgentSession" = session
        self._runner: TurnRunner = runner
        self._replies: ReplyWriter = replies
        self._boundary_inbox: ChannelBoundaryInbox = boundary_inbox
        self._interval: float = interval if interval is not None else poll_interval_from_env()
        self._task: Optional[asyncio.Task[None]] = None
        self._run_task: Optional["asyncio.Task[TurnOutcomeDAO]"] = None
        self._running_row: Optional[ChannelMessageDAO] = None
        self._running_row_started: bool = False
        self._queue_admission_lock: asyncio.Lock = asyncio.Lock()
        self._paused_reason: Optional[str] = None
        self._stopping: bool = False
        self._started: bool = False
        self._display: Optional[ChannelDisplaySink] = display
        self._auto_run: bool = auto_run
        self._note_display: ChannelNoteDisplay = (
            note_display if note_display is not None else ChannelNoteDisplay(sink=display)
        )
        self._participant_id: UUID = channel_participant_id_for_session(session_id=self._session.session_id)
        self._durable_inbox: bool = durable_inbox
        self._participant_name: str = participant_name or f"slo {str(self._participant_id)[:8]}"

    @property
    def boundary_inbox(self) -> ChannelBoundaryInbox:
        """Return the boundary inbox this poller refreshes (108.2).

        Returns:
            ChannelBoundaryInbox: The adapter shared with the session's agent.
        """
        return self._boundary_inbox

    @property
    def participant_id(self) -> UUID:
        """Return the agent participant id this poller serves (108.1 §2.3).

        Returns:
            UUID: The queue identity of the served session.
        """
        return self._participant_id

    @property
    def busy(self) -> bool:
        """Return whether a run is currently executing.

        Returns:
            bool: True while one run task is in flight.
        """
        return self._run_task is not None and not self._run_task.done()

    @property
    def paused(self) -> Optional[str]:
        """Return the pause reason while paused.

        Returns:
            Optional[str]: The reason passed to ``pause``, or ``None``.
        """
        return self._paused_reason

    async def start(self) -> None:
        """Register the agent participant, recover, and start the loop task.

        Recovery (108.1 §6): rows left pending by an earlier process whose id
        is already in ``events.jsonl`` (via ``channel_message_id``) are
        accepted; when operator rows (``ParticipantDAO.is_operator``: any user
        participant, or an unknown sender) remain pending the poller starts
        paused so the operator decides with ``/queue resume``. Rows from other
        agents and systems (a workflow that reported while the session was
        closed) never pause it (108.3 §6) — the same operator rule that
        admission and closure apply.
        """
        if self._started:
            return
        self._started = True
        await self._gateway.register_agent(
            session_id=self._participant_id,
            name=self._participant_name,
            durable_inbox=self._durable_inbox,
        )
        await self._recover_on_start()
        self._stopping = False
        self._task = asyncio.create_task(self._loop())

    async def stop(self, *, reason: str) -> None:
        """Finish the current run, settle it, stop the loop, and close the agent.

        The loop task is cancelled first, so the in-flight run (if any) is
        awaited and settled here: its reply is written exactly once (the
        reply id is stable, so a settlement the cancelled loop had already
        begun is not duplicated) and the model is never run again. A
        settlement that still fails is logged; the row stays accepted.

        The note display is closed next, on every exit path: a note render
        the cancelled tick left running is cancelled and joined before
        ``stop`` returns, so the caller can retire the borrowed UI knowing no
        render of this delivery can still publish into it.

        Args:
            reason (str): Cancellation reason recorded on pending rows, e.g.
                ``session_closed``.
        """
        self._stopping = True
        try:
            await self._finish_loop_and_last_run()
        finally:
            await self._note_display.close()
        await self._gateway.close_agent(session_id=self._participant_id, reason=reason)
        self._started = False

    async def _finish_loop_and_last_run(self) -> None:
        """Cancel the poll loop, then await and settle the in-flight run, if any."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._run_task is not None:
            await asyncio.gather(self._run_task, return_exceptions=True)
            try:
                await self._settle_finished_run()
            except Exception as exc:  # noqa: BLE001 -- closing must still close the agent
                log_error(msg=f"channel poller could not settle its last run on stop: {exc}")

    def pause(self, *, reason: str) -> None:
        """Stop starting new runs; sends are still accepted.

        Args:
            reason (str): Why the poller paused, shown by ``/queue``.
        """
        self._paused_reason = reason

    def resume(self) -> None:
        """Continue after a pause."""
        self._paused_reason = None
        self._gateway.local_wake(recipient_id=self._participant_id).set()

    async def pending_prompts(self) -> list[ChannelMessageDAO]:
        """Return the session's queued prompt rows in display order.

        Forced rows come first (108.2 §4 ordering); this is the list the
        ``/queue`` commands number, force and cancel against. The row this
        poller is running is excluded even before its first event stamps
        ``accepted_at``: it is running, not queued, so a queue position never
        names it.

        Returns:
            list[ChannelMessageDAO]: Queued prompt rows, forced first.
        """
        async with self._queue_admission_lock:
            return await self._read_pending_prompts()

    async def _read_pending_prompts(self) -> list[ChannelMessageDAO]:
        """Read pending prompt rows while the caller owns queue admission.

        WHAT: Excludes the row reserved for the current run before its first
            event is accepted.
        WHO: Queue listing and the poller's atomic admission step call this.
        WHEN: While ``_queue_admission_lock`` serializes row selection against
            operator cancellation.

        Returns:
            list[ChannelMessageDAO]: Pending prompts in gateway display order.
        """
        rows: list[ChannelMessageDAO] = await self._gateway.pending_inbound(
            recipient_id=self._participant_id,
        )
        running_id: Optional[UUID] = self._running_row.id if self._running_row is not None else None
        return [row for row in rows if row.message_type == "prompt" and row.id != running_id]

    async def cancel_queued(self, *, message_id: UUID) -> bool:
        """Cancel a queued prompt as its recipient agent's operator.

        WHAT: Serializes prompt cancellation against the pending-read and run
            reservation, and records the standard ``operator`` cancellation.
        WHO: The TUI channel adapter delegates operator cancellation here.
        WHEN: Before a prompt's first event is accepted; a reserved or running
            prompt is never cancelled.

        Args:
            message_id (UUID): Queued prompt to cancel.

        Returns:
            bool: ``True`` only when the still-queued prompt was cancelled.
        """
        async with self._queue_admission_lock:
            if self._running_row is not None and self._running_row.id == message_id:
                return False
            message: Optional[ChannelMessageDAO] = await self._gateway.get(message_id=message_id)
            if (
                message is None
                or message.recipient_id != self._participant_id
                or message.message_type != "prompt"
                or message.accepted_at is not None
                or message.cancelled_at is not None
            ):
                return False
            return await self._gateway.cancel(
                message_id=message_id,
                by=self._participant_id,
                reason="operator",
            )

    async def force(self, *, message_id: UUID) -> bool:
        """Force one of this agent's pending rows into the current run (108.2).

        The agent participant itself is the actor (it owns its queue); the
        gateway refuses rows that are accepted or cancelled, which the caller
        surfaces as ``already running``.

        Args:
            message_id (UUID): Row to force.

        Returns:
            bool: ``True`` when the row is now forced and still pending.
        """
        return await self._gateway.force(message_id=message_id, by=self._participant_id)

    @property
    def current_run_task(self) -> Optional["asyncio.Task[TurnOutcomeDAO]"]:
        """Return the in-flight run task, or ``None`` (abort-escalation identity).

        Callers bind a hard-cancel timer to the exact task captured at abort
        time so a later run is never cancelled by a stale escalation.

        Returns:
            Optional[asyncio.Task[TurnOutcomeDAO]]: The run task in flight.
        """
        return self._run_task

    def cancel_current(self) -> bool:
        """Hard-cancel the current run task (``/abort`` escalation).

        Returns:
            bool: True when a running task was cancelled.
        """
        if self._run_task is None or self._run_task.done():
            return False
        self._run_task.cancel()
        return True

    async def _recover_on_start(self) -> None:
        """Accept rows already in history; pause when other rows remain."""
        pending: list[ChannelMessageDAO] = await self._gateway.pending_inbound(
            recipient_id=self._participant_id,
        )
        if not pending:
            return
        known_ids: set[str] = set()
        if self._session.history_store is not None:
            try:
                known_ids = await self._session.channel_message_ids_in_history()
            except Exception as exc:  # noqa: BLE001 — recovery must not kill startup
                log_warning(msg=f"channel recovery history scan failed: {exc}")
        operator_leftover: list[ChannelMessageDAO] = []
        for row in pending:
            if str(row.id) in known_ids:
                await self._gateway.accept(message_id=row.id)
            elif await self._is_operator_row(message=row):
                operator_leftover.append(row)
        if operator_leftover:
            self._paused_reason = "recovered"
            log_warning(
                msg=(
                    f"channel poller recovered {len(operator_leftover)} pending row(s); "
                    "paused (use /queue resume)"
                )
            )

    async def _is_operator_row(self, *, message: ChannelMessageDAO) -> bool:
        """Return whether an operator sent a row (an unknown sender counts as one).

        Args:
            message (ChannelMessageDAO): A pending inbound row.

        Returns:
            bool: ``True`` unless the sender is a known agent or system.
        """
        sender: Optional[ParticipantDAO] = await self._gateway.get_participant(
            participant_id=message.sender_id
        )
        return sender is None or sender.is_operator

    async def _loop(self) -> None:
        """The poll loop: run one tick per wake or interval, then wait again.

        A tick processes at most one run transition (settle or start). The
        wait is skipped only when the previous tick left known work (a run
        settled with rows possibly pending behind it), so a queued next run
        starts immediately. Sends that arrive during a tick re-set the wake
        after it is cleared, so they are never lost to a full interval.
        """
        wake: asyncio.Event = self._gateway.local_wake(recipient_id=self._participant_id)
        last_heartbeat: float = asyncio.get_event_loop().time()
        work_left_behind: bool = False
        while not self._stopping:
            if not work_left_behind:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=self._interval)
                except asyncio.TimeoutError:
                    pass
            work_left_behind = False
            if self._stopping:
                return
            now: float = asyncio.get_event_loop().time()
            if now - last_heartbeat >= _HEARTBEAT_INTERVAL_SECONDS:
                last_heartbeat = now
                try:
                    await self._gateway.heartbeat(participant_id=self._participant_id)
                except Exception as exc:  # noqa: BLE001 — heartbeat is best-effort
                    log_warning(msg=f"channel heartbeat failed: {exc}")
            # Refresh the forced-row snapshot every tick — including while a
            # run is in flight — so the agent's stop decision (``has_forced``)
            # sees a forced row within one poll interval (108.2 F5).
            try:
                await self._boundary_inbox.refresh()
            except Exception as exc:  # noqa: BLE001 — a bad snapshot must not kill the loop
                log_warning(msg=f"channel forced-snapshot refresh failed: {exc}")
            # Rows shown but never run settle before run transitions: notices
            # display-and-accept, notes display-once and record when idle
            # (108.3 §5).
            try:
                await self._settle_display_rows()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the loop must survive a bad row
                log_error(msg=f"channel poller display settlement failed: {exc}")
            if self._run_task is not None:
                if self._run_task.done():
                    try:
                        await self._settle_finished_run()
                        work_left_behind = True
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001 — the loop must survive a bad run
                        log_error(msg=f"channel poller run settlement failed: {exc}")
            elif (
                self._auto_run
                and self._paused_reason is None
                and not self._session.is_running
                and self._session.preparation_status == "ready"
            ):
                # One run owner at a time (108.1): while the session runs a
                # run this poller does not own (a direct ``invoke`` caller),
                # the tick defers so no queued row is started into a busy
                # session and cancelled.
                try:
                    work_left_behind = await self._start_next_pending_prompt()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — the loop must survive a bad row
                    log_error(msg=f"channel poller iteration failed: {exc}")
            # Drop the wake signal only now: anything sent during this tick
            # re-sets the event and makes the next wait return at once.
            wake.clear()

    async def _settle_display_rows(self) -> None:
        """Settle every pending ``notice`` and ``note`` row for this session.

        A ``notice`` is display-only: shown through the sink (when wired),
        then accepted — it never enters model context (108.3 §2). A ``note``
        is shown once per id through the shared ``ChannelNoteDisplay`` (which
        first retries notes whose earlier render failed); when the session is
        idle it is recorded via ``record_workflow_update`` and accepted, so it
        joins the context at the next run without ever starting one. While
        the session runs, the pending note stays in the queue for the boundary
        inbox to take before forced prompts — notes never revive a run
        (108.3 O2).
        """
        await self._note_display.show_owed()
        rows: list[ChannelMessageDAO] = await self._gateway.pending_inbound(
            recipient_id=self._participant_id,
        )
        for row in rows:
            if row.message_type == "notice":
                await self._show(message=row)
                await self._gateway.accept(message_id=row.id)
                continue
            if row.message_type != "note":
                continue
            await self._note_display.show_once(message=row)
            if not self._session_idle() or not await self._is_still_pending(message=row):
                continue
            try:
                await self._session.record_workflow_update(
                    text=row.message_contents,
                    message_id=str(row.id),
                    workflow_id=workflow_id_from_note(text=row.message_contents),
                )
            except Exception as exc:  # noqa: BLE001 — an unrecorded note is retried next tick
                log_warning(msg=f"channel note record failed: {exc}")
                continue
            await self._gateway.accept(message_id=row.id)

    async def _is_still_pending(self, *, message: ChannelMessageDAO) -> bool:
        """Return whether a row read at the start of this tick is still pending.

        A display can outlast a whole run, during which the boundary may take
        and accept the note; recording it again would put it in the context
        twice.

        Args:
            message (ChannelMessageDAO): A row from this tick's pending read.

        Returns:
            bool: ``True`` while the row is neither accepted nor cancelled.
        """
        current: Optional[ChannelMessageDAO] = await self._gateway.get(message_id=message.id)
        return current is not None and current.accepted_at is None and current.cancelled_at is None

    def _session_idle(self) -> bool:
        """Return whether the session currently runs nothing this poller must not interleave.

        Returns:
            bool: ``True`` when no run task is in flight and the session is not
                running.
        """
        run_settling: bool = self._run_task is not None and not self._run_task.done()
        return not run_settling and not self._session.is_running

    async def _show(self, *, message: ChannelMessageDAO) -> None:
        """Hand one row to the display sink when one is wired.

        Args:
            message (ChannelMessageDAO): The notice or note being displayed.
        """
        if self._display is None:
            return
        await self._display.show(message=message)

    async def _settle_finished_run(self) -> None:
        """Settle one finished run; its state is retained until settlement succeeds.

        Settlement maps the finished task to its effects: a run that never
        started cancels its row (``start_failed``); an aborted run pauses the
        poller; every started run gets exactly one reply. When an effect
        raises, the run task and row stay in place, so the next tick (or
        ``stop``) retries the settlement from the same finished task without
        rerunning the model. Each effect is idempotent (stable reply id,
        guarded cancel, pause), so a retry never duplicates one.
        """
        run_task: Optional["asyncio.Task[TurnOutcomeDAO]"] = self._run_task
        row: Optional[ChannelMessageDAO] = self._running_row
        if run_task is None or row is None:
            self._run_task = None
            self._running_row = None
            return
        outcome: Optional[TurnOutcomeDAO] = self._finished_run_outcome(run_task=run_task)
        if outcome is None:
            self._paused_reason = "aborted"
        elif outcome.status == "not_started":
            await self._gateway.cancel(message_id=row.id, reason="start_failed")
        else:
            if outcome.status == "aborted":
                self._paused_reason = "aborted"
            await self._replies.write(request=row, outcome=outcome)
        self._run_task = None
        self._running_row = None
        self._running_row_started = False
        self._boundary_inbox.release(message_id=row.id)

    def _finished_run_outcome(self, *, run_task: "asyncio.Task[TurnOutcomeDAO]") -> Optional[TurnOutcomeDAO]:
        """Return how a finished run task ended, without re-awaiting it.

        A cancelled run that never reached its first event leaves its row
        pending (``None``: it runs again after ``/queue resume``); one that
        had started is an aborted turn. A runner that raised is a failed turn
        once started, otherwise a turn that never started.

        Args:
            run_task (asyncio.Task[TurnOutcomeDAO]): The finished run task.

        Returns:
            Optional[TurnOutcomeDAO]: The outcome to settle, or ``None`` for a
                cancelled run that never started.
        """
        if run_task.cancelled():
            return TurnOutcomeDAO(status="aborted") if self._running_row_started else None
        error: Optional[BaseException] = run_task.exception()
        if error is None:
            return run_task.result()
        log_error(msg=f"channel turn runner raised: {error!r}")
        return TurnOutcomeDAO(
            status="failed" if self._running_row_started else "not_started",
            error=f"run failed: {error}",
        )

    async def _start_next_pending_prompt(self) -> bool:
        """Reserve and start the first pending prompt row (forced first, FIFO).

        Returns:
            bool: ``True`` when a run was started and more prompt rows may
                still be pending behind it (the loop skips its wait once).
        """
        async with self._queue_admission_lock:
            prompts: list[ChannelMessageDAO] = await self._read_pending_prompts()
            if not prompts:
                return False
            row: ChannelMessageDAO = prompts[0]
            # Reserve the run's own row before cancellation or another
            # admission can observe the still-unaccepted row as pending.
            self._boundary_inbox.reserve(message_id=row.id)
            self._running_row = row
            self._running_row_started = False
            self._run_task = asyncio.create_task(
                self._runner.run(message=row, on_started=self._accept_running_row)
            )
            self._run_task.add_done_callback(
                lambda _task: self._gateway.local_wake(recipient_id=self._participant_id).set()
            )
            return len(prompts) > 1

    async def _accept_running_row(self) -> None:
        """Accept the reserved row when its runner yields the first event.

        WHAT: Records first-event admission and persists ``accepted_at`` for
            the poller's reserved row.
        WHO: The ``TurnRunner`` callback created by ``_start_next_pending_prompt``.
        WHEN: Once the underlying session invoke yields its first event.
        """
        row: Optional[ChannelMessageDAO] = self._running_row
        if row is None:
            raise RuntimeError("Channel poller has no reserved prompt to accept.")
        self._running_row_started = True
        await self._gateway.accept(message_id=row.id)
