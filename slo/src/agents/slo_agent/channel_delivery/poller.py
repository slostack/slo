"""ChannelPoller — one asyncio task per agent session watching the queue (108.1).

Loop (108.1 §5.3): wait on the local wake event or the poll interval; skip
while busy, paused or the session is not ready; take the first pending
``prompt`` row FIFO; run it through the injected ``TurnRunner``; stamp
``accepted_at`` via the runner's ``on_started`` callback; write the reply;
pause after an aborted run.
"""

from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING
from uuid import UUID, NAMESPACE_URL, uuid5

from config.logger import log_error, log_warning
from config.timeout_resolver import positive_float_env

from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO, TurnRunner
from src.channels.dao import ChannelMessageDAO
from src.channels.gateway import ChannelGateway

if TYPE_CHECKING:
    from src.agents.slo_agent.sessions.service import SloAgentSession

__all__ = ["ChannelPoller", "poll_interval_from_env"]

_DEFAULT_POLL_INTERVAL_SECONDS: float = 0.5
_HEARTBEAT_INTERVAL_SECONDS: float = 5.0


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
        self._participant_id: UUID = channel_participant_id_for_session(session_id=self._session.session_id)

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
        accepted; when other rows remain pending the poller starts paused so
        the operator decides with ``/queue resume``.
        """
        if self._started:
            return
        self._started = True
        session_uuid = self._participant_id
        await self._gateway.register_agent(
            session_id=session_uuid,
            name=f"slo {str(session_uuid)[:8]}",
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
        leftover: list[ChannelMessageDAO] = []
        for row in pending:
            if str(row.id) in known_ids:
                await self._gateway.accept(message_id=row.id)
            else:
                leftover.append(row)
        if leftover:
            self._paused_reason = "recovered"
            log_warning(
                msg=f"channel poller recovered {len(leftover)} pending row(s); paused (use /queue resume)"
            )

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
                self._paused_reason is None
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
