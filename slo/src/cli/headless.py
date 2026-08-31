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
import sys
import time
from typing import Optional

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier
from config.timeout_resolver import positive_float_env
from src.cli.headless_events import emit_lifecycle_event

__all__ = ["HeadlessRunner"]

_FALLBACK_WORKFLOW_ID: str = "wf-unknown"

# Maps run terminal kinds to the matching lifecycle kind for stderr.
_TERMINAL_KIND_TO_LIFECYCLE: dict[str, str] = {
    "run_completed": "headless_run_completed",
    "run_aborted": "headless_run_aborted",
}


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
            notifier (Optional[WorkflowNotifier]): Injectable notifier for
                tests. Ignored when ``notify_session_id`` is ``None``.
        """
        self._config: SessionConfigDAO = config
        self._orchestrator_mode: bool = orchestrator_mode
        self._notify_session_id: Optional[str] = notify_session_id
        self._injected_notifier: Optional[WorkflowNotifier] = notifier
        self._notifier: Optional[WorkflowNotifier] = None
        self._started_sent: bool = False
        self._last_spawn_result_json: str = "{}"
        self._terminal_kind: str = "run_failed"
        self._terminal_content: str = ""
        self._last_event_at: float = time.monotonic()
        self._heartbeat_phase: str = "awaiting_provider_stream"
        self._heartbeat_attempt: int = 1

    async def invoke(self, *, prompt: str) -> int:
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
        session: SloAgentSession = SloAgentSession.build(config=self._config)
        emit_lifecycle_event(
            kind="headless_session_started",
            session_id=session.session_id,
            message="headless runner starting",
            payload={
                "workdir": str(self._config.workdir),
                "history_enabled": bool(self._config.enable_history),
            },
        )
        emit_lifecycle_event(
            kind="headless_session_resolved",
            session_id=session.session_id,
            message="session id resolved",
        )
        if self._orchestrator_mode:
            from src.agents.slo_agent.orchestrator.bootstrap import (  # noqa: PLC0415
                OrchestratorSessionBootstrap,
            )
            OrchestratorSessionBootstrap.attach(session=session, headless=True)
            emit_lifecycle_event(
                kind="headless_orchestrator_attached",
                session_id=session.session_id,
                message="sub-agent pool attached",
            )
        session.subscribe(handler=self._emit)
        self._notifier = self._resolve_notifier(orchestrator_session_id=session.session_id)
        await self._notify_started(prompt=prompt)
        heartbeat_task: asyncio.Task[None] = asyncio.create_task(
            self._emit_headless_heartbeats(session_id=session.session_id)
        )
        try:
            async for _event in session.invoke(text=prompt):
                pass
        finally:
            await self._cancel_and_await_heartbeat_task(heartbeat_task=heartbeat_task)
        await self._notify_terminal()
        lifecycle_kind: str = _TERMINAL_KIND_TO_LIFECYCLE.get(
            self._terminal_kind,
            "headless_run_failed",
        )
        emit_lifecycle_event(
            kind=lifecycle_kind,  # type: ignore[arg-type]
            session_id=session.session_id,
            message=f"run ended with {self._terminal_kind}",
            payload={"terminal_kind": self._terminal_kind},
        )
        return self._exit_code_for_terminal_kind(kind=self._terminal_kind)

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
        self._last_event_at = time.monotonic()
        self._heartbeat_phase = self._phase_for_event(event=event)
        self._heartbeat_attempt = self._attempt_for_event(event=event)
        if event.is_terminal:
            self._terminal_kind = event.kind
            if not event.is_sub_agent_event:
                self._terminal_content = event.content or ""
        sys.stdout.write(event.model_dump_json() + "\n")
        sys.stdout.flush()
        await self._maybe_notify_phase(event=event)

    async def _emit_headless_heartbeats(self, *, session_id: str) -> None:
        """Emit stderr-only liveness records until the active run reaches a terminal state.

        WHAT: Periodically emits a bounded ``headless_status`` lifecycle event.
        WHO: Started by ``invoke`` alongside the session stream for child-process supervisors.
        DATA FLOW: Writes safe phase, age, and attempt fields to stderr via lifecycle JSONL.
        LIFETIME: Runs until ``invoke`` cancels and awaits it before terminal lifecycle output.
        """
        heartbeat_seconds: float = positive_float_env(
            primary_name="SLO_HEADLESS_HEARTBEAT_SECONDS",
            default=15.0,
        )
        while True:
            await asyncio.sleep(heartbeat_seconds)
            emit_lifecycle_event(
                kind="headless_status",
                session_id=session_id,
                message="headless heartbeat",
                payload={
                    "phase": self._heartbeat_phase,
                    "last_event_age_seconds": max(0, int(time.monotonic() - self._last_event_at)),
                    "attempt": self._heartbeat_attempt,
                },
            )

    async def _cancel_and_await_heartbeat_task(self, *, heartbeat_task: asyncio.Task[None]) -> None:
        """Cancel and await the run-owned heartbeat without masking run completion."""
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
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
        return WorkflowNotifier(
            target_session_id=self._notify_session_id,
            orchestrator_session_id=orchestrator_session_id,
            workflow_id=os.environ.get("SLO_WORKFLOW_ID", _FALLBACK_WORKFLOW_ID),
        )

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

    async def _notify_terminal(self) -> None:
        """Send the terminal workflow message matching the run's terminal kind."""
        if self._notifier is None:
            return
        if self._terminal_kind == "run_completed":
            await self._notifier.completed(
                synthesis=self._terminal_content,
                result_json=self._last_spawn_result_json,
            )
            return
        await self._notifier.failed(
            error=f"{self._terminal_kind}: {self._terminal_content or 'no terminal output'}",
        )

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

    @staticmethod
    def _exit_code_for_terminal_kind(*, kind: str) -> int:
        """Map a terminal event kind to the POSIX exit code.

        Args:
            kind (str): Terminal event kind: ``run_completed``, ``run_aborted``,
                or ``run_failed``.

        Returns:
            int: ``0`` for ``run_completed``, ``2`` for ``run_aborted``,
                ``1`` for all other values (including ``run_failed``).
        """
        return {"run_completed": 0, "run_aborted": 2}.get(kind, 1)
