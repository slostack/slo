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

import sys

from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.cli.headless_events import emit_lifecycle_event

__all__ = ["HeadlessRunner"]

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
    ) -> None:
        """Bind the runner to its session config.

        Args:
            config (SessionConfigDAO): Fully-resolved session config.
            orchestrator_mode (bool, optional): When ``True`` a ``SubAgentPool``
                will be attached before the run so the agent can spawn sub-agents.
                Defaults to ``False``.
        """
        self._config: SessionConfigDAO = config
        self._orchestrator_mode: bool = orchestrator_mode
        self._terminal_kind: str = "run_failed"

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
            OrchestratorSessionBootstrap.attach(session=session)
            emit_lifecycle_event(
                kind="headless_orchestrator_attached",
                session_id=session.session_id,
                message="sub-agent pool attached",
            )
        session.subscribe(handler=self._emit)
        async for _event in session.invoke(text=prompt):
            pass
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
        event kind so ``invoke`` can derive the exit code after the session ends.
        Flushes after every write so downstream consumers (``SubAgentProcess``)
        receive events as they arrive, not buffered.

        Args:
            event (AgentStreamEventDAO): The event to serialise and emit.
        """
        if event.is_terminal:
            self._terminal_kind = event.kind
        sys.stdout.write(event.model_dump_json() + "\n")
        sys.stdout.flush()

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
