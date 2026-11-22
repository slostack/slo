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
from typing import Optional, Protocol, TYPE_CHECKING, runtime_checkable
from uuid import UUID, NAMESPACE_URL, uuid5

from config.logger import log_error, log_warning
from config.timeout_resolver import positive_float_env

from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
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


@runtime_checkable
class ChannelDisplaySink(Protocol):
    """Where the poller hands rows that must be shown but not run (108.3 §5)."""

    async def show(self, *, message: ChannelMessageDAO) -> None:
        """Display one channel row (notice or note) to this channel's user.

        Args:
            message (ChannelMessageDAO): The row being displayed.
        """
        ...


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
        self._paused_reason: Optional[str] = None
        self._stopping: bool = False
        self._started: bool = False
        self._display: Optional[ChannelDisplaySink] = display
        self._auto_run: bool = auto_run
        self._shown_note_ids: set[UUID] = set()
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
        """Finish the current run, stop the loop, and close the agent.

        Args:
            reason (str): Cancellation reason recorded on pending rows, e.g.
                ``session_closed``.
        """
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._run_task is not None and not self._run_task.done():
            await asyncio.gather(self._run_task, return_exceptions=True)
        await self._gateway.close_agent(session_id=self._participant_id, reason=reason)
        self._started = False

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
        """Return the session's pending prompt rows in display order.

        Forced rows come first (108.2 §4 ordering); this is the list the
        ``/queue`` commands number and force against.

        Returns:
            list[ChannelMessageDAO]: Pending prompt rows, forced first.
        """
        rows: list[ChannelMessageDAO] = await self._gateway.pending_inbound(
            recipient_id=self._participant_id,
        )
        return [row for row in rows if row.message_type == "prompt"]

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
                # run this poller does not own (the inbox chat_turn bridge),
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
        is shown once per id; when the session is idle it is recorded via
        ``record_workflow_update`` and accepted, so it joins the context at
        the next run without ever starting one. While the session runs, the
        pending note stays in the queue for the boundary inbox to take before
        forced prompts — notes never revive a run (108.3 O2).
        """
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
            if row.id not in self._shown_note_ids:
                await self._show(message=row)
                self._shown_note_ids.add(row.id)
            if not self._session_idle():
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
        """Finish one completed run: accept semantics, pause on abort, reply."""
        run_task: asyncio.Task[TurnOutcomeDAO] | None = self._run_task
        row: Optional[ChannelMessageDAO] = self._running_row
        if run_task is None or row is None:
            self._run_task = None
            self._running_row = None
            return
        try:
            outcome: TurnOutcomeDAO = await run_task
        except asyncio.CancelledError:
            self._run_task = None
            self._boundary_inbox.release(message_id=row.id)
            self._paused_reason = "aborted"
            return
        self._run_task = None
        self._running_row = None
        self._boundary_inbox.release(message_id=row.id)
        if outcome.status == "not_started":
            await self._gateway.cancel(message_id=row.id, reason="start_failed")
            return
        if outcome.status == "aborted":
            self._paused_reason = "aborted"
        await self._replies.write(request=row, outcome=outcome)

    async def _start_next_pending_prompt(self) -> bool:
        """Start a run for the first pending prompt row (forced first, FIFO).

        Returns:
            bool: ``True`` when a run was started and more prompt rows may
                still be pending behind it (the loop skips its wait once).
        """
        prompts: list[ChannelMessageDAO] = await self.pending_prompts()
        if not prompts:
            return False
        row: ChannelMessageDAO = prompts[0]
        # Reserve the run's own row so the agent's first boundary cannot take
        # it again as steering (the row is still pending until its first event
        # stamps ``accepted_at``).
        self._boundary_inbox.reserve(message_id=row.id)
        self._running_row = row

        async def _accept() -> None:
            await self._gateway.accept(message_id=row.id)

        run_task: asyncio.Task[TurnOutcomeDAO] = asyncio.create_task(
            self._runner.run(message=row, on_started=_accept)
        )
        self._run_task = run_task
        # A finished run must settle promptly (reply row, next queued run),
        # so its completion wakes the loop even when the wake was consumed.
        run_task.add_done_callback(
            lambda _task: self._gateway.local_wake(recipient_id=self._participant_id).set()
        )
        return len(prompts) > 1
