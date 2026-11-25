"""HeadlessRunner — run one agent loop with no UI and emit a JSONL event stream.

Sub-spec 01-sub-agents 01.a: headless one-shot invocation mode.

``TyperDispatch.run_headless()`` constructs one runner per ``slo run``
invocation. The runner drives a single ``SloAgentSession`` to completion and
writes every ``AgentStreamEventDAO`` as one newline-terminated JSON line to
``sys.stdout``. The terminal event kind maps to the POSIX exit code the
``slo run`` command raises via ``typer.Exit``.

History is disabled by default for sub-agent headless runs — the orchestrator
links children by session id rather than by replaying their individual
histories.  Operators can opt in with ``--enable-history``.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4
from types import FrameType
from typing import TYPE_CHECKING, Awaitable, Callable, Coroutine, Optional, TextIO, cast

from src.auth.credential_dao import CredentialDAO
from src.auth.credential_resolver import CredentialResolver
from config.logger import log_warning
from config.timeout_resolver import positive_float_env
from src.agents.model_catalog.service import ModelCatalogService
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.history.filesystem_store import default_history_root
from src.agents.slo_agent.orchestrator.dao import (
    TERMINAL_KIND_TO_HEADLESS_LIFECYCLE,
    ChildControlCapabilityDAO,
    SubAgentResultDAO,
    SubAgentStatusDAO,
    build_cleanup_summary,
    exit_code_for_terminal_kind,
    project_fleet_entries,
    run_state_for_terminal_kind,
)
from src.agents.slo_agent.orchestrator.child_abort import ChildAbortController, ChildAbortStore
from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout
from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
from src.agents.slo_agent.orchestrator.process_probe import ProcessProbe
from src.agents.slo_agent.orchestrator.spawn_env import CHANNEL_PARENT_ID_ENV, CHANNEL_PARTICIPANT_NAME_ENV
from src.agents.slo_agent.orchestrator.reaper import (
    FleetReaper,
    IdentityVerificationOutcome,
    ReapOutcome,
)
from src.cli.headless_channel import HeadlessTurnRunner, emit_channel_turn_marker, followup_turn_cap
from src.cli.headless_events import emit_lifecycle_event
from src.cli.headless_watchdog import HeadlessWatchdog

if TYPE_CHECKING:
    from src.bridges.claude.sdk.protocol import SloBridgeAdapterProtocol
    from langchain_core.tools import BaseTool

    from src.channels.dao import ChannelMessageDAO
    from src.channels.gateway import ChannelGateway
    from src.agents.slo_agent.channel_delivery.poller import ChannelPoller
    from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
    from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool

__all__ = ["HeadlessRunner"]

_FALLBACK_WORKFLOW_ID: str = "wf-unknown"
_SUB_AGENT_LIFECYCLE_KINDS: frozenset[str] = frozenset(
    {"sub_agent_spawned", "sub_agent_completed", "sub_agent_failed", "sub_agent_aborted"}
)
COOPERATIVE_ABORT_GRACE_SECONDS: float = positive_float_env(
    primary_name="SLO_HEADLESS_COOPERATIVE_ABORT_GRACE_SECONDS",
    default=5.0,
)
"""Maximum time a cooperative abort may wait before cancelling the blocked stream."""


class _HeadlessJSONLWriter:
    """Serialize already-redacted events to a borrowed text stream."""

    @classmethod
    def write(cls, *, event: AgentStreamEventDAO, stream: TextIO) -> None:
        """Write and flush one JSONL record after runner redaction/bookkeeping.

        Args:
            event: Already-redacted event; this writer owns no credentials.
            stream: Borrowed output, never retained or closed.

        Raises:
            OSError: Stream write or flush fails; no retry is attempted.
        """
        stream.write(event.model_dump_json() + "\n")
        stream.flush()


class HeadlessRunner:
    """Runs a single prompt through one ``SloAgentSession`` and streams JSONL to stdout.

    Single-use per ``slo run`` invocation. ``invoke()`` builds the session,
    subscribes the stdout emitter, drives the session to completion, and
    returns the POSIX exit code derived from the terminal event kind.

    Attributes:
        _config (SessionConfigDAO): Fully-resolved session config from
            ``TyperDispatch._build_session_config``.
        _terminal_kind (str): Set by ``_emit`` when a terminal event is seen;
            used by ``invoke`` to derive the exit code after the session ends.
    """

    def __init__(
        self,
        *,
        config: SessionConfigDAO,
        orchestrator_mode: bool = False,
        notify_session_id: Optional[str] = None,
        notifier: Optional[WorkflowNotifier] = None,
        session_preparer: Optional[Callable[[SessionConfigDAO], Awaitable[SloAgentSession]]] = None,
        bridge_adapter_class: Optional[type["SloBridgeAdapterProtocol"]] = None,
        output_stream: Optional[TextIO] = None,
        channel_gateway: Optional["ChannelGateway"] = None,
        history_root: Optional[Path] = None,
        cooperative_abort_grace_seconds: Optional[float] = None,
    ) -> None:
        """Bind the runner to its session config.

        Args:
            config (SessionConfigDAO): Fully-resolved session config.
            orchestrator_mode (bool, optional): When ``True`` a ``SubAgentPool``
                will be attached before the run so the agent can spawn sub-agents.
                Defaults to ``False``.
            notify_session_id (Optional[str]): Session id whose inbox receives
                workflow lifecycle notifications (spec 57.a.3). ``None`` keeps
                behaviour byte-identical to a plain headless run — no notifier
                is constructed and nothing is enqueued.
            output_stream: Borrowed output, never closed. None uses current stdout
                at emission time, preserving dynamic output capture.
            notifier (Optional[WorkflowNotifier]): Injectable notifier for
                tests. Ignored when ``notify_session_id`` is ``None``.
            channel_gateway (Optional[ChannelGateway]): Injectable shared
                channel gateway for tests (108.3). Production builds
                ``ChannelGateway.default()`` in channel mode only (a workflow
                run or a pool child).
            history_root (Optional[Path]): History root for workflow status and
                abort-request files; ``None`` uses ``default_history_root()``.
            cooperative_abort_grace_seconds (Optional[float]): How long a stop
                order waits for the session to abort itself before the blocked
                stream is cancelled; ``None`` uses
                ``SLO_HEADLESS_COOPERATIVE_ABORT_GRACE_SECONDS``.
        """
        self._output_stream: Optional[TextIO] = output_stream
        self._session_preparer = session_preparer
        self._bridge_adapter_class = bridge_adapter_class
        self._session_id: str = config.session_id or str(uuid4())
        self._config: SessionConfigDAO = config.model_copy(update={"session_id": self._session_id})
        self._orchestrator_mode: bool = orchestrator_mode
        self._notify_session_id: Optional[str] = notify_session_id
        self._injected_notifier: Optional[WorkflowNotifier] = notifier
        self._notifier: Optional[WorkflowNotifier] = None
        self._channel_gateway: Optional["ChannelGateway"] = None
        self._channel_poller: Optional["ChannelPoller"] = None
        self._fleet_snapshot_supplier: Optional[Callable[[], tuple[list[dict[str, object]], int]]] = None
        self._fleet_entries_supplier: Optional[Callable[[], list[SubAgentStatusDAO]]] = None
        self._started_sent: bool = False
        self._last_spawn_result_json: str = "{}"
        self._terminal_kind: str = "run_failed"
        self._terminal_received: bool = False
        self._terminal_content: str = ""
        self._operation_credential: Optional[CredentialDAO] = None
        self._last_event_at: float = time.monotonic()
        self._heartbeat_phase: str = "awaiting_provider_stream"
        self._heartbeat_attempt: int = 1
        self._session: Optional[SloAgentSession] = None
        self._status_store: Optional[OrchestratorStatusStore] = None
        self._abort_reason: Optional[str] = None
        self._abort_requested: Optional[asyncio.Event] = None
        self._child_control: Optional[ChildAbortController] = None
        self._injected_channel_gateway: Optional["ChannelGateway"] = channel_gateway
        self._terminal_generation: int = 0
        self._channel_parent_id: Optional[UUID] = self._channel_parent_id_from_env()
        self._history_root: Optional[Path] = history_root
        self._cooperative_abort_grace_seconds: float = (
            cooperative_abort_grace_seconds
            if cooperative_abort_grace_seconds is not None
            else COOPERATIVE_ABORT_GRACE_SECONDS
        )

    async def invoke(self, *, prompt: str) -> int:
        """Run one prompt, releasing its private capture after terminal cleanup.

        Args:
            prompt (str): Task to run through the prepared session.

        Returns:
            int: Existing terminal-kind exit code.
        """
        result: Optional[int] = None
        try:
            result = await self._invoke(prompt=prompt)
        except BaseException:
            await self._finalize_agent_resources()
            try:
                await self._close_external_reporting()
            finally:
                self._operation_credential = None
                await self._close_owned_channel_gateway()
            raise
        try:
            await self._finalize_agent_resources()
        except Exception:
            self._report_cleanup_failure()
            if result == 0:
                result = 1
        finally:
            try:
                await self._close_external_reporting()
            finally:
                self._operation_credential = None
                await self._close_owned_channel_gateway()
        return result

    async def _finalize_agent_resources(self) -> None:
        """Close model resources independently of reporting cleanup."""
        if self._session is None:
            return
        try:
            await self._session.close_agent_resources()
        except Exception:
            self._report_cleanup_failure()
            raise

    async def _close_external_reporting(self) -> None:
        """Join adopted reporting owners before releasing the runner's session."""
        if self._session is None:
            return
        try:
            try:
                await self._session.close_external_reporting()
            except Exception:
                self._report_cleanup_failure()
        finally:
            try:
                await self._session.finish_retired_reporting_cleanup()
            except Exception:
                self._report_cleanup_failure()

    def _report_cleanup_failure(self) -> None:
        """Emit fixed best-effort diagnostics without replacing the run outcome."""
        try:
            sys.stderr.write("Headless reporting cleanup failed.\n")
        except Exception:
            pass

    async def _invoke(self, *, prompt: str) -> int:
        """Own process cleanup across preparation, adoption, activation and execution."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        self._abort_requested = asyncio.Event()
        previous = self._install_sigterm_handler(loop=loop)
        try:
            return await self._invoke_with_signal_owner(prompt=prompt)
        finally:
            try:
                self._restore_sigterm_handler(previous=previous)
            except Exception:
                self._report_cleanup_failure()
            finally:
                try:
                    await self._shutdown_model_catalog()
                except Exception:
                    self._report_cleanup_failure()

    async def _invoke_with_signal_owner(self, *, prompt: str) -> int:
        """Run one prompt to completion and return the POSIX exit code.

        Builds the session, optionally promotes it to orchestrator mode when
        ``orchestrator_mode=True``, subscribes the stdout emitter, then drives
        the session to completion. Emits lifecycle events to stderr at each
        phase boundary so parent orchestrators and capture pipelines can
        monitor progress without parsing stdout.

        Args:
            prompt (str): The task prompt to run headlessly.

        Returns:
            int: ``0`` when the run completed normally, ``2`` when aborted,
                ``1`` on any failure or unexpected terminal kind.
        """
        emit_lifecycle_event(
            kind="headless_session_started",
            session_id=self._session_id,
            message="headless runner starting",
            payload={
                "workdir": str(self._config.workdir),
                "history_enabled": bool(self._config.enable_history),
            },
        )
        emit_lifecycle_event(
            kind="headless_session_resolved",
            session_id=self._session_id,
            message="session id resolved",
        )
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        # Channel tools bind at session construction, so the gateway opens first.
        self._channel_gateway = await self._open_channel_gateway()
        self._config = self._config_with_child_messaging()
        preparation_task: asyncio.Task[Optional[SloAgentSession]] = asyncio.create_task(
            self._prepare_session()
        )
        try:
            session: Optional[SloAgentSession] = await self._await_preparation_or_abort(
                preparation_task=preparation_task,
            )
            if session is None:
                return await self._complete_preparation_failure()
            self._session = session
            await session.start_external_reporting()
        except asyncio.CancelledError:
            return await self._complete_preparation_abort()
        finally:
            await self._cancel_preparation_task_if_needed(preparation_task=preparation_task)
        if self._orchestrator_mode:
            self._attach_orchestrator(session=session)
            self._fleet_entries_supplier = self._resolve_fleet_entries_supplier(session=session)
            self._fleet_snapshot_supplier = self._build_fleet_snapshot_supplier()
            emit_lifecycle_event(
                kind="headless_orchestrator_attached",
                session_id=session.session_id,
                message="sub-agent pool attached",
            )
        session.subscribe(handler=self._emit)
        self._status_store = self._build_status_store(session_id=session.session_id)
        self._notifier = self._resolve_notifier(orchestrator_session_id=session.session_id)
        await self._notify_started(prompt=prompt)

        def request_abort_from_watchdog(reason: str) -> None:
            """Schedule the watchdog's cooperative abort request on the runner loop."""
            loop.call_soon_threadsafe(self._request_cooperative_abort, reason)

        watchdog: HeadlessWatchdog = HeadlessWatchdog(
            session_id=session.session_id,
            state_supplier=self._heartbeat_state_snapshot,
            status_store=self._status_store,
            abort_request_path=self._abort_request_path(session_id=session.session_id),
            parent_pid=self._parent_pid_from_env(),
            on_abort=request_abort_from_watchdog,
        )
        watchdog.start()
        try:
            await self._start_child_control()
            await self._start_workflow_channel(session=session)
            await self._drain_session_stream_until_abort(session=session, prompt=prompt)
            # Follow-up turns stay under the same supervision as the main run
            # (watchdog abort file, parent-death probe, SIGTERM, child control).
            await self._run_follow_up_turns()
        except Exception as exc:
            if not self._terminal_received:
                await self._emit(AgentStreamEventDAO(kind="run_failed", content=str(exc)))
        finally:
            try:
                await self._stop_workflow_channel()
            finally:
                try:
                    await self._close_child_control()
                except Exception:
                    self._report_cleanup_failure()
                finally:
                    try:
                        watchdog.stop()
                    except Exception:
                        self._report_cleanup_failure()
        self._write_orphan_status_if_needed(session_id=session.session_id)
        await self._write_terminal_status()
        await self._notify_terminal()
        lifecycle_kind: str = TERMINAL_KIND_TO_HEADLESS_LIFECYCLE.get(
            self._terminal_kind,
            "headless_run_failed",
        )
        emit_lifecycle_event(
            kind=lifecycle_kind,  # type: ignore[arg-type]
            session_id=session.session_id,
            message=f"run ended with {self._terminal_kind}",
            payload={"terminal_kind": self._terminal_kind},
        )
        return exit_code_for_terminal_kind(kind=self._terminal_kind)

    async def _await_preparation_or_abort(
        self,
        *,
        preparation_task: asyncio.Task[Optional[SloAgentSession]],
    ) -> Optional[SloAgentSession]:
        """Await preparation unless the SIGTERM controller requests its cancellation.

        WHAT: Races the one preparation task against the preparation abort event.
        WHO: ``invoke`` calls this immediately after installing its SIGTERM handler.
        WHEN: Before session construction, subscribers, watchdog, or inference.

        Args:
            preparation_task (asyncio.Task[Optional[SloAgentSession]]): The active
                session-preparation task.

        Returns:
            Optional[SloAgentSession]: The prepared session or ``None`` on safe preparation failure.

        Raises:
            asyncio.CancelledError: If SIGTERM requests preparation cancellation.
        """
        if self._abort_requested is None:
            raise RuntimeError("abort controller was not initialized")
        abort_task: asyncio.Task[bool] = asyncio.create_task(self._abort_requested.wait())
        try:
            completed, _pending = await asyncio.wait(
                {preparation_task, abort_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if preparation_task in completed:
                return await preparation_task
            preparation_task.cancel()
            await asyncio.gather(preparation_task, return_exceptions=True)
            raise asyncio.CancelledError()
        finally:
            abort_task.cancel()
            await asyncio.gather(abort_task, return_exceptions=True)

    @staticmethod
    async def _cancel_preparation_task_if_needed(
        *,
        preparation_task: asyncio.Task[Optional[SloAgentSession]],
    ) -> None:
        """Cancel and join an unfinished preparation task during early runner exit.

        WHAT: Prevents a cancelled or failed preparation path from leaving gateway work behind.
        WHO: ``invoke`` executes this from its pre-session ``finally`` block.
        WHEN: After preparation returns, fails, or receives SIGTERM and before signal restoration.

        Args:
            preparation_task (asyncio.Task[Optional[SloAgentSession]]): The task that owns preparation.
        """
        if preparation_task.done():
            return
        preparation_task.cancel()
        await asyncio.gather(preparation_task, return_exceptions=True)

    async def _prepare_session(self) -> Optional[SloAgentSession]:
        """Prepare dynamic routes before invocation; preserve direct construction.

        Called once by invoke before any subscriber, watchdog, or inference exists.
        Failure uses the existing terminal status and notification owners.

        Returns:
            Optional[SloAgentSession]: Prepared session, or None after safe failure.
        """
        if self._session_preparer is not None:
            return await self._session_preparer(self._config)
        routes: tuple[str, ...] = SloAgentSession._configured_model_names(config=self._config)
        if not any(route.startswith(("openrouter:", "claude-bridge:")) for route in routes):
            return SloAgentSession.build(config=self._config)
        try:
            return await SloAgentSession.prepare(
                config=self._config, bridge_adapter_class=self._bridge_adapter_class
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return None

    async def _complete_preparation_failure(self) -> int:
        """Emit one terminal failure after preparation has failed safely.

        WHAT: Reuses the ordinary terminal owners with the materialized session ID.
        WHO: ``invoke`` calls this after its preparation controller catches failure.
        WHEN: Before session construction, subscription, or provider inference.

        Returns:
            int: The failure exit code.
        """
        await self._report_preparation_terminal(kind="run_failed")
        return 1

    async def _complete_preparation_abort(self) -> int:
        """Emit one terminal abort when preparation is cancelled by the operator.

        WHAT: Preserves cancellation semantics while ensuring durable terminal state.
        WHO: ``invoke`` calls this when preparation raises ``CancelledError``.
        WHEN: Before a prepared session reaches normal watchdog setup.

        Returns:
            int: The standard abort exit code.
        """
        await self._report_preparation_terminal(kind="run_aborted")
        return exit_code_for_terminal_kind(kind="run_aborted")

    async def _report_preparation_terminal(self, *, kind: str) -> None:
        """Publish one safe preparation terminal state through existing owners.

        WHAT: Emits terminal output, status, notification, and lifecycle records
            without exposing preparation exception text.
        WHO: Preparation failure and cancellation paths share this method.
        WHEN: Before a session can be subscribed or invoked.

        Args:
            kind (str): ``run_failed`` or ``run_aborted`` terminal kind.
        """
        session_id: str = self._session_id
        self._status_store = self._build_status_store(session_id=session_id)
        self._channel_gateway = await self._open_channel_gateway()
        self._notifier = self._resolve_notifier(orchestrator_session_id=session_id)
        await self._emit(
            AgentStreamEventDAO(
                kind=kind,  # type: ignore[arg-type]
                content=(
                    self._preparation_failure_guidance()
                    if kind == "run_failed"
                    else "Model preparation aborted."
                ),
                metadata={"session_id": session_id, "failure_scope": "model_preparation"},
            )
        )
        await self._write_terminal_status()
        await self._notify_terminal()
        emit_lifecycle_event(
            kind=TERMINAL_KIND_TO_HEADLESS_LIFECYCLE.get(kind, "headless_run_failed"),  # type: ignore[arg-type]
            session_id=session_id,
            message=f"run ended with {kind}",
            payload={"terminal_kind": kind},
        )

    def _preparation_failure_guidance(self) -> str:
        """Select fixed runtime-specific guidance without exposing raw preparation errors."""
        if (self._config.model_name or "").startswith("claude-bridge:"):
            return (
                "Claude bridge preparation failed. Check Claude Code /login outside Slo and native overrides; "
                "then retry a fresh bridge session. Native transcripts may persist with Slo history off."
            )
        return "Model preparation failed; refresh OpenRouter models or select a direct model."

    async def _shutdown_model_catalog(self) -> None:
        """Drain process-owned catalog refresh work when the headless application exits.

        WHAT: Delegates global catalog task ownership to its explicit shutdown seam.
        WHO: Called only by ``invoke()`` after its session/watchdog lifecycle ends.
        WHEN: Once per headless process, never from an individual session teardown.
        """
        await ModelCatalogService.shutdown()

    async def _emit(self, event: AgentStreamEventDAO) -> None:
        """Write one event to stdout as a single newline-terminated JSON line.

        Registered as the session subscriber by ``invoke``. Records the terminal
        event kind so ``invoke`` can derive the exit code after the session ends,
        and taps ``spawn_sub_agents`` results into the workflow notifier when
        ``--notify-session`` is active. Flushes after every write so downstream
        consumers (``SubAgentProcess``) receive events as they arrive, not
        buffered.

        Args:
            event (AgentStreamEventDAO): The event to serialise and emit.
        """
        captured = CredentialResolver.operation_credential()
        if captured is not None:
            self._operation_credential = captured
        if self._operation_credential is not None:
            with CredentialResolver.bind_operation_credential(credential=self._operation_credential):
                event = AgentStreamEventDAO.model_validate_json(
                    CredentialResolver.redact_openrouter_text(text=event.model_dump_json())
                )
        self._last_event_at = time.monotonic()
        self._heartbeat_phase = self._phase_for_event(event=event)
        self._heartbeat_attempt = self._attempt_for_event(event=event)
        if event.is_terminal:
            self._terminal_kind = event.kind
            if not event.is_sub_agent_event:
                self._terminal_received = True
                self._terminal_content = event.content or ""
                self._terminal_generation += 1
        _HeadlessJSONLWriter.write(
            event=event, stream=self._output_stream if self._output_stream is not None else sys.stdout
        )
        await self._maybe_notify_phase(event=event)
        await self._maybe_notify_fleet(event=event)

    def _build_status_store(self, *, session_id: str) -> Optional[OrchestratorStatusStore]:
        """Build workflow status storage for the resolved session identity.

        WHAT: Binds durable self-reporting evidence to the session that build resolved.
        WHO: Called by invoke before it constructs the watchdog.
        WHEN: Only workflow-mode runs with SLO_WORKFLOW_ID write this evidence.

        Args:
            session_id (str): Session identifier resolved by SloAgentSession.build.

        Returns:
            Optional[OrchestratorStatusStore]: Bound store in workflow mode, else None.
        """
        workflow_id: Optional[str] = os.environ.get("SLO_WORKFLOW_ID")
        if workflow_id is None:
            return None
        return OrchestratorStatusStore(
            history_root=self._resolved_history_root(),
            orchestrator_session_id=session_id,
            workflow_id=workflow_id,
        )

    def _abort_request_path(self, *, session_id: str) -> Optional[Path]:
        """Return this resolved workflow run's durable abort-request path.

        WHAT: Builds the control path paired with the active status store.
        WHO: Called by invoke while configuring HeadlessWatchdog.
        WHEN: Only after workflow-mode status storage was bound.

        Args:
            session_id (str): Session identifier resolved by SloAgentSession.build.

        Returns:
            Optional[Path]: Canonical abort request path, or None outside workflow mode.
        """
        if self._status_store is None:
            return None
        return OrchestrationLayout.abort_request_path(
            history_root=self._resolved_history_root(),
            orchestrator_session_id=session_id,
        )

    def _resolved_history_root(self) -> Path:
        """Return the injected history root, else the process default.

        Returns:
            Path: Root holding workflow status and abort-request files.
        """
        return self._history_root if self._history_root is not None else default_history_root()

    @staticmethod
    def _parent_pid_from_env() -> Optional[int]:
        """Return a numeric child parent pid; watchdog construction calls this once."""
        raw: Optional[str] = os.environ.get("SLO_PARENT_PID")
        if raw is None or not raw.isdigit():
            return None
        return int(raw)

    def _heartbeat_state_snapshot(self) -> tuple[str, int]:
        """Return a thread-safe phase and attempt snapshot to HeadlessWatchdog."""
        return self._heartbeat_phase, self._heartbeat_attempt

    def _request_cooperative_abort(self, reason: str) -> None:
        """Request session abort once; watchdog and SIGTERM handler call this funnel.

        WHAT: Schedules the terminal pool close before the session's turn abort,
            so the pool never reopens once a stop order arrived. The close is
            scheduled only when a pool is attached; a plain headless run has none.

        Args:
            reason (str): First canonical shutdown reason observed for this run.
        """
        if self._abort_reason is not None:
            return
        self._abort_reason = reason
        if self._abort_requested is not None:
            self._abort_requested.set()
        if self._attached_pool() is not None:
            asyncio.ensure_future(self._shutdown_pool_if_attached())
        if self._session is not None:
            self._session.abort()

    async def _drain_session_stream_until_abort(
        self,
        *,
        session: SloAgentSession,
        prompt: str,
        channel_message_id: Optional[UUID] = None,
        on_first_event: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        """Drain the session stream or force a bounded cooperative abort.

        WHAT: Runs the provider stream in a cancellable task so watchdog stop orders
            cannot wait forever for the next graph update.
        WHO: Called by invoke after it starts HeadlessWatchdog, and by
            ``run_channel_turn`` for each follow-up turn.
        WHEN: Once per headless run or follow-up turn, until normal completion
            or shutdown.

        Args:
            session (SloAgentSession): Session whose stream produces the run events.
            prompt (str): Prompt passed unchanged to the session stream.
            channel_message_id (Optional[UUID]): Channel row this run answers;
                recorded on the persisted ``user_message`` (108.1 §6 recovery key).
            on_first_event (Optional[Callable[[], Awaitable[None]]]): Awaited once,
                after the session yields its first event — by then the
                ``user_message`` history record is written.
        """
        if self._abort_requested is None:
            raise RuntimeError("abort controller was not initialized")
        stream_work: Coroutine[object, object, None] = (
            self._drain_session_stream(session=session, prompt=prompt)
            if channel_message_id is None
            else self._drain_channel_turn_stream(
                session=session,
                prompt=prompt,
                channel_message_id=channel_message_id,
                on_first_event=on_first_event,
            )
        )
        stream_task: asyncio.Task[None] = asyncio.create_task(stream_work)
        abort_task: asyncio.Task[bool] = asyncio.create_task(self._abort_requested.wait())
        try:
            completed, _pending = await asyncio.wait(
                {stream_task, abort_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if stream_task in completed:
                await stream_task
                return
            await self._allow_cooperative_abort(stream_task=stream_task)
        finally:
            abort_task.cancel()
            await asyncio.gather(abort_task, return_exceptions=True)

    async def _drain_session_stream(self, *, session: SloAgentSession, prompt: str) -> None:
        """Drain session events inside the task controlled by the abort controller.

        WHAT: Consumes every session event while session subscribers emit stdout.
        WHO: Called by _drain_session_stream_until_abort.
        WHEN: Runs until the session naturally ends or its task is cancelled.

        Args:
            session (SloAgentSession): Active session to consume.
            prompt (str): Prompt passed to the active session.
        """
        async for _event in session.invoke(text=prompt):
            pass

    async def _drain_channel_turn_stream(
        self,
        *,
        session: SloAgentSession,
        prompt: str,
        channel_message_id: UUID,
        on_first_event: Optional[Callable[[], Awaitable[None]]],
    ) -> None:
        """Drain one channel turn's events, calling back once on the first event.

        WHAT: Like ``_drain_session_stream`` but records the channel row id on
            the persisted ``user_message`` and awaits ``on_first_event`` after
            the first event, i.e. after that history record exists.
        WHO: Called by _drain_session_stream_until_abort for a channel turn.
        WHEN: Once per follow-up turn, inside the abort-controlled task.

        Args:
            session (SloAgentSession): Active session to consume.
            prompt (str): The row's text.
            channel_message_id (UUID): The channel row this turn answers.
            on_first_event (Optional[Callable[[], Awaitable[None]]]): First-event callback.
        """
        pending_first_event: Optional[Callable[[], Awaitable[None]]] = on_first_event
        async for _event in session.invoke(text=prompt, channel_message_id=channel_message_id):
            if pending_first_event is None:
                continue
            callback: Callable[[], Awaitable[None]] = pending_first_event
            pending_first_event = None
            await callback()

    async def _allow_cooperative_abort(self, *, stream_task: asyncio.Task[None]) -> None:
        """Give session.abort a bounded chance before forcing terminal abort.

        WHAT: Waits for normal aborted output, then cancels a blocked provider stream.
        WHO: Called by _drain_session_stream_until_abort after a stop order.
        WHEN: Once when SIGTERM, an abort file, or parent death requests shutdown.

        Args:
            stream_task (asyncio.Task[None]): Cancellable task draining the session stream.
        """
        try:
            await asyncio.wait_for(asyncio.shield(stream_task), timeout=self._cooperative_abort_grace_seconds)
        except asyncio.TimeoutError:
            stream_task.cancel()
            await asyncio.gather(stream_task, return_exceptions=True)
        if self._terminal_kind != "run_aborted":
            await self._emit(AgentStreamEventDAO(kind="run_aborted", content="<aborted>"))

    def _install_sigterm_handler(
        self, *, loop: asyncio.AbstractEventLoop
    ) -> Callable[[int, Optional[FrameType]], None] | int | None:
        """Route SIGTERM to cooperative abort; invoke restores the prior handler on teardown."""

        def handler(signum: int, frame: Optional[FrameType]) -> None:
            """Schedule operator abort from Python's synchronous signal boundary."""
            loop.call_soon_threadsafe(self._request_cooperative_abort, "operator_abort")

        return signal.signal(signal.SIGTERM, handler)

    @staticmethod
    def _restore_sigterm_handler(
        *,
        previous: Callable[[int, Optional[FrameType]], None] | int | None,
    ) -> None:
        """Restore the prior SIGTERM handler after HeadlessRunner stops its watchdog."""
        signal.signal(signal.SIGTERM, previous)

    async def _shutdown_pool_if_attached(self) -> None:
        """Close the pool terminally when the cooperative funnel receives a stop order.

        WHAT: Delegates the terminal close and child drain to its single owner.
        WHO: Scheduled by _request_cooperative_abort for watchdog and SIGTERM requests.
        WHEN: Once after the first cooperative abort reason wins.
        """
        pool: Optional[SubAgentPool] = self._attached_pool()
        if pool is None:
            return
        await pool.close_and_drain()

    async def _write_terminal_status(self) -> None:
        """Write terminal workflow evidence only after a fully resolved fleet drain.

        WHAT: Withholds self-reporting until every durable running entry is resolved.
        WHO: Called by invoke before it sends the terminal workflow notification.
        WHEN: At every workflow-mode run end.
        """
        if self._status_store is None:
            return
        await self._await_abort_pool_shutdown()
        is_drained: bool = await self._drain_fleet()
        if not is_drained:
            log_warning(msg="terminal_status_withheld_for_unresolved_fleet")
            return
        self._status_store.write_terminal(
            state=run_state_for_terminal_kind(kind=self._terminal_kind),  # type: ignore[arg-type]
            exit_code=exit_code_for_terminal_kind(kind=self._terminal_kind),
            phase=self._heartbeat_phase,
        )

    async def _await_abort_pool_shutdown(self) -> None:
        """Join pool close before terminal fleet draining.

        WHAT: Waits for the shared terminal close rather than racing its records.
        WHO: Called by _write_terminal_status after a cooperative abort request.
        WHEN: Only when the runner accepted an abort reason.
        """
        if self._abort_reason is None:
            return
        pool: Optional[SubAgentPool] = self._attached_pool()
        if pool is None:
            return
        await pool.close_and_drain()

    async def _start_child_control(self) -> None:
        """Publish child control for this run when an explicit launch owner exists.

        WHAT: Builds the controller from the attached pool and starts it. A
            composition failure (a pool identity that fails validation, such as
            an unsafe launch owner) or a publication failure is a fixed
            diagnostic: execution continues with child control unavailable, and
            no accepting capability exists.
        WHO: Called by ``_invoke`` after pool and notifier setup.
        WHEN: Once, immediately before the session stream starts.
        """
        try:
            self._child_control = self._build_child_control()
            if self._child_control is not None:
                await self._child_control.start()
        except (OSError, ValueError):
            self._child_control = None
            log_warning(msg="child_control_unavailable")

    def _build_child_control(self) -> Optional[ChildAbortController]:
        """Compose the runner-owned controller, or None when this run has no owner context.

        WHAT: Binds the store to the pool's own history root and the accepting
            capability to the pool's immutable run, owner and parent identity.
            The owner comes from the ``--notify-session`` launch context bound at
            attach time, never from a request.
        WHO: Called by ``_start_child_control``.
        WHEN: Once per run, after orchestrator attach.

        Returns:
            Optional[ChildAbortController]: Unstarted controller, or None for a plain
                run or a run without an explicit launch owner.
        """
        pool: Optional[SubAgentPool] = self._attached_pool()
        if pool is None or self._notify_session_id is None:
            return None
        capability: ChildControlCapabilityDAO = pool.child_control_capability().model_copy(
            update={"accepting": True}
        )
        return ChildAbortController(
            pool=pool,
            store=ChildAbortStore(
                history_root=pool.history_root, orchestrator_session_id=capability.orchestrator_session_id
            ),
            capability=capability,
        )

    async def _close_child_control(self) -> None:
        """Join child-control shutdown to completion, even across repeated cancellation.

        WHAT: Withdraws the capability, stops polling, joins accepted child
            operations and flushes receipts. A cancellation of this runner while
            waiting is deferred until shutdown completes, then re-raised.
        WHO: Called from ``_invoke``'s ``finally`` on success, error and cancellation.
        WHEN: Before ``_write_terminal_status`` drains the fleet.

        Raises:
            asyncio.CancelledError: The runner was cancelled while shutdown was joined.
        """
        if self._child_control is None:
            return
        closing: asyncio.Future[None] = asyncio.ensure_future(self._child_control.close())
        interrupted: bool = False
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                interrupted = True
        closing.result()
        if interrupted:
            raise asyncio.CancelledError

    def _attached_pool(self) -> Optional[SubAgentPool]:
        """Return the bootstrap-attached pool when this session owns one.

        WHAT: Reads the session's additive pool accessor without constructing a pool.
        WHO: Called by abort and terminal cleanup helpers.
        WHEN: Only on orchestrator-mode cleanup paths.

        Returns:
            Optional[SubAgentPool]: Attached pool, or None for a plain headless run.
        """
        if self._session is None:
            return None
        from src.agents.slo_agent.orchestrator.pool import SubAgentPool  # noqa: PLC0415

        pool: object = getattr(self._session, "_sub_agent_pool", None)
        return pool if isinstance(pool, SubAgentPool) else None

    async def _drain_fleet(self) -> bool:
        """Resolve every running fleet entry before terminal status is persisted.

        WHAT: Reaps verified children and records dead or recycled child entries.
        WHO: Called by _write_terminal_status.
        WHEN: On every workflow-mode terminal path.

        Returns:
            bool: True only when no durable fleet entry remains running.
        """
        pool: Optional[SubAgentPool] = self._attached_pool()
        if pool is None:
            return True
        for entry in pool.registry.snapshot():
            if entry.status != "running" or entry.pid is None:
                continue
            await self._reap_one_straggler(pool=pool, entry=entry)
        return all(entry.status not in {"pending", "running"} for entry in pool.registry.snapshot())

    async def _reap_one_straggler(self, *, pool: SubAgentPool, entry: SubAgentStatusDAO) -> None:
        """Resolve one running entry without signaling an unverified identity.

        WHAT: Reaps exact children and records dead or recycled entries as terminal.
        WHO: Called by _drain_fleet for each durable running fleet entry.
        WHEN: Before HeadlessRunner writes terminal orchestrator evidence.
        """
        if entry.pid is None:
            return
        identity: IdentityVerificationOutcome = FleetReaper.child_identity_outcome(
            pid=entry.pid,
            session_id=entry.session_id,
        )
        if identity == "unreadable":
            log_warning(msg="fleet_entry_pid_unreadable", session_id=entry.session_id, pid=entry.pid)
            return
        if identity == "recycled_pid":
            pool.registry.mark_terminal(
                session_id=entry.session_id,
                execution_id=entry.execution_id,
                status="failed",
                answer="recorded pid belongs to a different process; not signalled",
                exit_code=1,
                terminal_reason="failed",
                terminated_by="sweep",
            )
            return
        if identity == "already_dead":
            pool.registry.mark_terminal(
                session_id=entry.session_id,
                execution_id=entry.execution_id,
                status="failed",
                answer="child was already absent during terminal drain",
                exit_code=1,
                terminal_reason="failed",
                terminated_by="sweep",
            )
            return
        outcome: ReapOutcome = await FleetReaper.reap(pid=entry.pid)
        if outcome == "unresolved":
            log_warning(msg="fleet_entry_pid_still_live", session_id=entry.session_id, pid=entry.pid)
            return
        pool.registry.mark_terminal(
            session_id=entry.session_id,
            execution_id=entry.execution_id,
            status="aborted" if outcome != "already_dead" else "failed",
            answer=(
                "reaped during terminal drain"
                if outcome != "already_dead"
                else "child exited during terminal drain"
            ),
            exit_code=-9 if outcome == "killed" else -15,
            terminal_reason="reaped_orphan" if outcome != "already_dead" else "failed",
            terminated_by="sweep",
        )

    def _write_orphan_status_if_needed(self, *, session_id: str) -> None:
        """Write child-owned orphan evidence only after parent-death shutdown.

        Args:
            session_id (str): Child session identifier for the terminal result.
        """
        if self._abort_reason != "orchestrator_died":
            return
        capture_dir: Optional[str] = os.environ.get("SLO_CAPTURE_DIR")
        if not capture_dir:
            return
        result: SubAgentResultDAO = SubAgentResultDAO(
            task_id="orphaned-child",
            session_id=session_id,
            status="aborted",
            exit_code=2,
            failure_code="orchestrator_died",
        )
        try:
            AtomicFileWriter.write_json(path=Path(capture_dir) / "status.json", model=result)
        except OSError:
            return

    @staticmethod
    def _phase_for_event(*, event: AgentStreamEventDAO) -> str:
        """Map a safe stream event category to its heartbeat phase label."""
        if event.kind.startswith("tool_"):
            return "running_tools"
        if event.kind in {"thinking_delta", "text_delta", "text_start", "thinking_start"}:
            return "streaming"
        return "awaiting_provider_stream"

    @staticmethod
    def _attempt_for_event(*, event: AgentStreamEventDAO) -> int:
        """Extract the safe provider attempt count when a stream event carries it."""
        attempt: object = event.metadata.get("attempt")
        return attempt if isinstance(attempt, int) and attempt > 0 else 1

    # ── workflow notification tap (spec 57.a.3) ──────────────────────────────

    def _attach_orchestrator(self, *, session: SloAgentSession) -> None:
        """Promote the headless session with its launch owner bound into the pool.

        WHAT: Delegates to the single pool composition owner, passing the
            ``--notify-session`` launch owner (or None, which resolves to this
            session) so owner identity never comes from a request payload.
        WHO: Called by ``_invoke`` for ``--orchestrator`` runs.
        WHEN: After session preparation, before the stream subscription.

        Args:
            session (SloAgentSession): Prepared headless session to promote.
        """
        from src.agents.slo_agent.orchestrator.bootstrap import (  # noqa: PLC0415
            OrchestratorSessionBootstrap,
        )

        OrchestratorSessionBootstrap.attach(
            session=session,
            headless=True,
            owner_session_id=self._notify_session_id,
            channel_gateway=self._channel_gateway,
        )

    def _resolve_notifier(self, *, orchestrator_session_id: str) -> Optional[WorkflowNotifier]:
        """Return the workflow notifier for this run, when one is requested.

        Args:
            orchestrator_session_id (str): This run's own session id.

        Returns:
            Optional[WorkflowNotifier]: ``None`` when ``--notify-session`` is
                absent (byte-identical legacy behaviour); the injected notifier
                when tests supplied one; else a fresh notifier bound to the
                target session, this orchestrator session, and the workflow id
                from ``SLO_WORKFLOW_ID``.
        """
        if self._notify_session_id is None:
            return None
        if self._injected_notifier is not None:
            return self._injected_notifier
        gateway: Optional["ChannelGateway"] = self._effective_channel_gateway()
        if gateway is None:
            return None
        return WorkflowNotifier(
            gateway=gateway,
            target_session_id=self._notify_session_id,
            orchestrator_session_id=orchestrator_session_id,
            workflow_id=os.environ.get("SLO_WORKFLOW_ID", _FALLBACK_WORKFLOW_ID),
            status_store=self._status_store,
        )

    def _effective_channel_gateway(self) -> Optional["ChannelGateway"]:
        """Return the injected or already-opened shared channel gateway, or ``None``.

        Returns:
            Optional[ChannelGateway]: The gateway for workflow mode.
        """
        return self._channel_gateway or self._injected_channel_gateway

    async def _open_channel_gateway(self) -> Optional["ChannelGateway"]:
        """Return the shared channel gateway in channel mode, or ``None``.

        Channel mode is a workflow run (``--notify-session``) or a pool child
        (``SLO_CHANNEL_PARENT_ID``). Other headless runs never touch the queue
        (108.3 O7). An unreachable shared database leaves the gateway ``None``;
        the notifier then swallows its sends and the channel lifecycle is
        skipped. Idempotent: a gateway already opened by this runner is reused.

        Returns:
            Optional[ChannelGateway]: The opened gateway, or ``None``.
        """
        if not self._is_channel_mode:
            return None
        if self._channel_gateway is not None:
            return self._channel_gateway
        if self._injected_channel_gateway is not None:
            return self._injected_channel_gateway
        try:
            from src.channels.gateway import ChannelGateway  # noqa: PLC0415

            return await ChannelGateway.default()
        except Exception as exc:  # noqa: BLE001 — a broken queue must not kill the workflow
            log_warning(msg=f"channel gateway unreachable: {exc}")
            return None

    async def _close_owned_channel_gateway(self) -> None:
        """Close the gateway this runner opened itself; an injected one stays open.

        Called once by ``invoke`` after every queue user (poller, follow-ups,
        terminal notification) is done.
        """
        gateway: Optional["ChannelGateway"] = self._channel_gateway
        self._channel_gateway = None
        if gateway is None or gateway is self._injected_channel_gateway:
            return
        try:
            await gateway.close()
        except Exception as exc:  # noqa: BLE001 — close is best-effort on the shutdown path
            log_warning(msg=f"channel gateway close failed: {exc}")

    @property
    def _is_channel_mode(self) -> bool:
        """Return whether this run is a workflow orchestrator or a pool child."""
        return self._notify_session_id is not None or self._channel_parent_id is not None

    def _config_with_child_messaging(self) -> SessionConfigDAO:
        """Return the config with ``send_message`` bound for a pool child (108.4 §5).

        A child may message only its parent (``to="parent"``); its notes are
        rate limited. Without a parent id or an open gateway the config is
        returned unchanged.

        Returns:
            SessionConfigDAO: The config the session is prepared from.
        """
        gateway: Optional["ChannelGateway"] = self._channel_gateway
        if self._channel_parent_id is None or gateway is None:
            return self._config
        from src.agents.slo_agent.channel_delivery.policy import MessagingPolicy  # noqa: PLC0415
        from src.agents.slo_agent.channel_delivery.poller import (  # noqa: PLC0415
            channel_participant_id_for_session,
        )
        from src.agents.slo_agent.channel_delivery.send_tool import SendMessageTool  # noqa: PLC0415

        self_id: UUID = channel_participant_id_for_session(session_id=self._session_id)
        policy: MessagingPolicy = MessagingPolicy(
            self_id=self_id,
            parent_id=self._channel_parent_id,
            children=lambda: [],
            launched_workflows=lambda: [],
        )
        send_tool: BaseTool = SendMessageTool.build(gateway=gateway, policy=policy, self_id=self_id)
        return self._config.model_copy(update={"extra_tools": [*(self._config.extra_tools or []), send_tool]})

    @staticmethod
    def _channel_parent_id_from_env() -> Optional[UUID]:
        """Return the parent's channel participant id a pool child was given, if valid."""
        raw: Optional[str] = os.environ.get(CHANNEL_PARENT_ID_ENV)
        if not raw:
            return None
        try:
            return UUID(raw)
        except ValueError:
            log_warning(msg="channel_parent_id_invalid")
            return None

    # ── workflow channel lifecycle (108.3 §5) ────────────────────────────

    @property
    def wired_session(self) -> Optional[SloAgentSession]:
        """Return the prepared session, or ``None`` before preparation ends.

        Returns:
            Optional[SloAgentSession]: The session this runner owns.
        """
        return self._session

    @property
    def terminal_generation(self) -> int:
        """Return how many non-child terminal events this runner has seen.

        Returns:
            int: Monotonic count; a follow-up turn compares generations to
                detect that its own run produced a terminal event.
        """
        return self._terminal_generation

    @property
    def terminal_kind(self) -> str:
        """Return the last non-child terminal event kind seen on stdout.

        Returns:
            str: e.g. ``run_completed`` or ``run_failed``.
        """
        return self._terminal_kind

    @property
    def terminal_content(self) -> str:
        """Return the last non-child terminal event content seen on stdout.

        Returns:
            str: The run's final text.
        """
        return self._terminal_content

    async def run_channel_turn(
        self,
        *,
        message: "ChannelMessageDAO",
        on_started: Callable[[], Awaitable[None]],
    ) -> None:
        """Run one channel prompt row as one supervised headless turn (108.3 §5).

        WHAT: Writes the ``channel_turn`` stdout marker, then drains the session
            under the same abort funnel as the main run, with the row id
            recorded on the persisted ``user_message``. ``on_started`` is awaited
            after the first session event, i.e. after that history record.
        WHO: ``HeadlessTurnRunner.run`` for each follow-up turn.
        WHEN: After the main run completed, while the watchdog still runs.

        Args:
            message (ChannelMessageDAO): The pending prompt row to run.
            on_started (Callable[[], Awaitable[None]]): Acceptance callback.

        Raises:
            RuntimeError: No session is prepared.
        """
        session: Optional[SloAgentSession] = self._session
        if session is None:
            raise RuntimeError("headless session is not prepared")
        emit_channel_turn_marker(output_stream=self._output_stream, message_id=message.id)
        await self._drain_session_stream_until_abort(
            session=session,
            prompt=message.message_contents,
            channel_message_id=message.id,
            on_first_event=on_started,
        )

    async def _start_workflow_channel(self, *, session: SloAgentSession) -> None:
        """Start the channel lifecycle in channel mode: register, keep the boundary live.

        Channel mode is a workflow run (``--notify-session``, 108.3) or a pool
        child (``SLO_CHANNEL_PARENT_ID``, 108.4); plain headless runs never
        touch the queue (108.3 O7). The poller runs with ``auto_run=False`` so
        it never starts turns itself — it keeps the boundary inbox snapshot
        fresh, settles notices and notes, and this runner owns every run. A
        child registers under ``SLO_CHANNEL_PARTICIPANT_NAME``.

        Args:
            session (SloAgentSession): The prepared session to serve.
        """
        gateway: Optional["ChannelGateway"] = self._channel_gateway
        if not self._is_channel_mode or gateway is None:
            return
        try:
            self._channel_poller = await session.start_channel_delivery(
                gateway=gateway,
                runner=HeadlessTurnRunner(runner=self),
                display=None,
                auto_run=False,
                participant_name=os.environ.get(CHANNEL_PARTICIPANT_NAME_ENV) or None,
            )
        except Exception as exc:  # noqa: BLE001 — a broken queue must not kill the workflow
            log_warning(msg=f"workflow channel lifecycle startup failed: {exc}")

    async def _run_follow_up_turns(self) -> None:
        """Run every normal pending prompt for W as its own turn, up to the cap.

        Runs only after a completed, un-aborted main run. Forced rows are
        taken by the agent's boundary inbox inside a run and are never
        follow-ups. Each turn's reply row goes back to the original sender. A
        turn that never started is cancelled as ``start_failed``.
        """
        gateway: Optional["ChannelGateway"] = self._channel_gateway
        poller: Optional["ChannelPoller"] = self._channel_poller
        if gateway is None or poller is None or self._session is None:
            return
        if self._terminal_kind != "run_completed" or self._abort_reason is not None:
            return
        from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter  # noqa: PLC0415

        replies: ReplyWriter = ReplyWriter(gateway=gateway)
        turn_runner: HeadlessTurnRunner = HeadlessTurnRunner(runner=self)
        participant_id: UUID = poller.participant_id
        for _turn in range(followup_turn_cap()):
            if self._abort_reason is not None:
                return
            try:
                rows: list["ChannelMessageDAO"] = await gateway.list_pending_inbound_messages(
                    recipient_id=participant_id
                )
                prompts: list["ChannelMessageDAO"] = [
                    row for row in rows if row.message_type == "prompt" and row.forced_at is None
                ]
                if not prompts:
                    return
                row: "ChannelMessageDAO" = prompts[0]

                async def _accept() -> None:
                    """Stamp the row accepted once its turn's history record exists."""
                    await gateway.accept(message_id=row.id)

                outcome: TurnOutcomeDAO = await turn_runner.run(message=row, on_started=_accept)
                if outcome.status == "not_started":
                    await gateway.cancel(message_id=row.id, reason="start_failed")
                    continue
                await replies.write(request=row, outcome=outcome)
            except Exception as exc:  # noqa: BLE001 — a broken queue must not kill the workflow
                log_warning(msg=f"workflow follow-up turn failed: {exc}")
                return

    async def _stop_workflow_channel(self) -> None:
        """Stop the poller and close W, cancelling whatever is still pending.

        ``close_agent`` flips the participant closed and cancels its pending
        inbound rows in one transaction with reason ``recipient_closed`` (or
        ``aborted`` when a stop order won), so no message can arrive after W
        stops listening (108.3 §2).
        """
        poller = self._channel_poller
        if poller is None:
            return
        self._channel_poller = None
        reason: str = "aborted" if self._abort_reason is not None else "recipient_closed"
        try:
            await poller.stop(reason=reason)
        except Exception as exc:  # noqa: BLE001 — close is best-effort on the shutdown path
            log_warning(msg=f"workflow channel close failed: {exc}")

    async def _notify_started(self, *, prompt: str) -> None:
        """Send the workflow_started note exactly once, before the first LLM call.

        Args:
            prompt (str): The workflow brief this run executes.
        """
        if self._notifier is None:
            return
        if self._started_sent:
            return
        self._started_sent = True
        await self._notifier.started(brief_preview=prompt)

    async def _maybe_notify_phase(self, *, event: AgentStreamEventDAO) -> None:
        """Send one phase update per orchestrator-level ``spawn_sub_agents`` result.

        Relayed sub-agent events (``sub_agent_id`` set) never count as phase
        boundaries — only this orchestrator's own tool results do.

        Args:
            event (AgentStreamEventDAO): The event under inspection.
        """
        if self._notifier is None:
            return
        if event.is_sub_agent_event:
            return
        if event.kind != "tool_result" or event.tool_name != "spawn_sub_agents":
            return
        result_text: str = event.content or "{}"
        self._last_spawn_result_json = result_text
        await self._notifier.phase_update(
            phase_summary=self._phase_summary(result_text=result_text),
        )

    async def _maybe_notify_fleet(self, *, event: AgentStreamEventDAO) -> None:
        """Send one fleet note for each relayed pool lifecycle event.

        WHAT: Reads the current compact snapshot and sends it through the notifier.
        WHO: Called by _emit after each session event reaches stdout.
        WHEN: Only for child lifecycle events in orchestrator-mode headless runs.

        Args:
            event (AgentStreamEventDAO): Stream event under inspection.
        """
        if self._notifier is None or self._fleet_snapshot_supplier is None:
            return
        if event.kind not in _SUB_AGENT_LIFECYCLE_KINDS:
            return
        entries, live_count = self._fleet_snapshot_supplier()
        await self._notifier.fleet_update(entries=entries, live_count=live_count)

    @staticmethod
    def _resolve_fleet_entries_supplier(
        *, session: SloAgentSession
    ) -> Optional[Callable[[], list[SubAgentStatusDAO]]]:
        """Return a pool registry reader after orchestrator bootstrap attaches one."""
        pool: object = getattr(session, "_sub_agent_pool", None)
        if pool is None:
            return None
        from src.agents.slo_agent.orchestrator.pool import SubAgentPool  # noqa: PLC0415

        return cast(SubAgentPool, pool).registry.snapshot

    def _build_fleet_snapshot_supplier(self) -> Optional[Callable[[], tuple[list[dict[str, object]], int]]]:
        """Build the compact-note projection over the attached pool registry reader."""
        supplier: Optional[Callable[[], list[SubAgentStatusDAO]]] = self._fleet_entries_supplier
        if supplier is None:
            return None
        return lambda: project_fleet_entries(entries=supplier())

    async def _notify_terminal(self) -> None:
        """Protect delayed terminal persistence with the admitted stream capture."""
        with CredentialResolver.bind_operation_credential(credential=self._operation_credential):
            await self._notify_terminal_with_capture()

    async def _notify_terminal_with_capture(self) -> None:
        """Send the terminal workflow message with final fleet cleanup accounting."""
        if self._notifier is None:
            return
        cleanup_summary: str = self._cleanup_summary()
        if self._terminal_kind == "run_completed":
            await self._notifier.completed(
                synthesis=self._terminal_content,
                result_json=self._last_spawn_result_json,
                cleanup_summary=cleanup_summary,
            )
            return
        if self._terminal_kind == "run_aborted":
            await self._notifier.aborted(
                reason=f"{self._terminal_kind}: {self._terminal_content or 'no terminal output'}",
                cleanup_summary=cleanup_summary,
            )
            return
        await self._notifier.failed(
            error=f"{self._terminal_kind}: {self._terminal_content or 'no terminal output'}",
            cleanup_summary=cleanup_summary,
        )

    def _cleanup_summary(self) -> str:
        """Return final fleet accounting when this headless run owns a pool."""
        if self._fleet_snapshot_supplier is None:
            return ""
        entries, live_count = self._fleet_snapshot_supplier()
        del entries
        if self._fleet_entries_supplier is None:
            return ""
        return build_cleanup_summary(entries=self._fleet_entries_supplier(), live_count=live_count)

    @staticmethod
    def _phase_summary(*, result_text: str) -> str:
        """Digest one ``OrchestratorResultDAO`` JSON into a one-line phase summary.

        Args:
            result_text (str): Raw ``spawn_sub_agents`` tool-result text.

        Returns:
            str: One-line summary (task count, completion flag, failed ids), or
                a fallback line when the result is not parseable JSON.
        """
        try:
            parsed: dict = json.loads(result_text)
        except (json.JSONDecodeError, TypeError):
            return "spawn_sub_agents finished (unparseable result)"
        if "error" in parsed:
            return f"spawn_sub_agents error: {parsed['error']}"
        task_count: int = len(parsed.get("results", []))
        all_completed: bool = bool(parsed.get("all_completed", False))
        failed_task_ids: list = parsed.get("failed_task_ids", [])
        summary: str = f"{task_count} task(s), all_completed={all_completed}"
        if failed_task_ids:
            summary += f", failed={failed_task_ids}"
        return summary
