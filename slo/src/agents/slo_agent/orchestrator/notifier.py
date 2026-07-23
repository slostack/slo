"""WorkflowNotifier — inbox writer for detached workflow lifecycle (spec 57.a.3).

Constructed by ``HeadlessRunner`` when ``--notify-session`` is present. The
notifier is the single writer of workflow inbox traffic: ``workflow_started``
and per-phase ``workflow_phase_update`` notes ship as ``context_note`` items,
and the terminal ``workflow_completed`` / ``workflow_failed`` messages ship as
``chat_turn`` items. Every enqueue failure is swallowed and logged — a
workflow must never die because the TUI's inbox is unavailable.
"""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from config.logger import log_info
from src.agents.slo_agent.history.filesystem_store import default_history_root
from src.agents.slo_agent.history.inbox.dao import (
    InboxDeliveryMode,
    InboxMessageKind,
    SessionInboxMessageDAO,
)
from src.agents.slo_agent.history.inbox.store import SessionInboxStore

__all__ = ["WorkflowNotifier"]

_BRIEF_PREVIEW_MAX_CHARS: int = 200


class WorkflowNotifier:
    """Enqueues workflow lifecycle messages into the owning session's inbox.

    Constructed by ``HeadlessRunner`` when ``--notify-session`` is present.
    Every public method is invoked by the runner's event tap at exactly one
    lifecycle boundary.
    """

    def __init__(
        self,
        *,
        target_session_id: str,
        orchestrator_session_id: str,
        workflow_id: str,
        inbox_store: Optional[SessionInboxStore] = None,
    ) -> None:
        """Bind the notifier to its target session and workflow identity.

        Args:
            target_session_id (str): TUI session whose inbox receives messages.
            orchestrator_session_id (str): This orchestrator's own session id.
            workflow_id (str): Workflow id from ``SLO_WORKFLOW_ID`` (or 'wf-unknown').
            inbox_store (Optional[SessionInboxStore]): Injectable store for tests.
        """
        self._target_session_id: str = target_session_id
        self._orchestrator_session_id: str = orchestrator_session_id
        self._workflow_id: str = workflow_id
        self._store: SessionInboxStore = inbox_store or SessionInboxStore(
            history_root=default_history_root(),
        )
        self._phase_index: int = 0

    async def started(self, *, brief_preview: str) -> None:
        """Enqueue the workflow_started context note. Invoked once, pre-first-LLM-call.

        Args:
            brief_preview (str): Leading slice of the workflow brief for display.
        """
        await self._safe_enqueue(
            kind="workflow_started",
            delivery_mode="context_note",
            title=f"{self._workflow_id} started",
            text=(
                f"[workflow {self._workflow_id}] started — orchestrator session "
                f"{self._orchestrator_session_id}. Brief: {brief_preview[:_BRIEF_PREVIEW_MAX_CHARS]}"
            ),
        )

    async def phase_update(self, *, phase_summary: str) -> None:
        """Enqueue one context_note phase update. Invoked per spawn_sub_agents result.

        Args:
            phase_summary (str): One-line digest built by the event tap from the
                ``OrchestratorResultDAO`` (task ids, all_completed, failed ids).
        """
        self._phase_index += 1
        await self._safe_enqueue(
            kind="workflow_phase_update",
            delivery_mode="context_note",
            title=f"{self._workflow_id} phase {self._phase_index}",
            text=f"[workflow {self._workflow_id}] phase {self._phase_index}: {phase_summary}",
        )

    async def completed(self, *, synthesis: str, result_json: str) -> None:
        """Enqueue the terminal chat_turn synthesis. Invoked once at run_completed.

        Args:
            synthesis (str): The orchestrator's final answer text.
            result_json (str): Last ``OrchestratorResultDAO`` JSON (or ``"{}"``).
        """
        await self._safe_enqueue(
            kind="workflow_completed",
            delivery_mode="chat_turn",
            title=f"{self._workflow_id} completed",
            text=(
                f"Workflow {self._workflow_id} completed. Present this synthesis to the "
                f"user and be ready for follow-ups.\n\nSynthesis:\n{synthesis}\n\n"
                f"Raw results JSON:\n{result_json}"
            ),
        )

    async def failed(self, *, error: str) -> None:
        """Enqueue the terminal chat_turn failure report. Invoked at run_failed/aborted.

        Args:
            error (str): Terminal error or state description.
        """
        await self._safe_enqueue(
            kind="workflow_failed",
            delivery_mode="chat_turn",
            title=f"{self._workflow_id} failed",
            text=(
                f"Workflow {self._workflow_id} did not complete. Error/state: {error}. "
                f"Summarise for the user; suggest /workflows and the visualizer for detail."
            ),
        )

    async def _safe_enqueue(
        self,
        *,
        kind: InboxMessageKind,
        delivery_mode: InboxDeliveryMode,
        title: str,
        text: str,
    ) -> None:
        """Build and enqueue one message; swallow and log every failure.

        The payload block carries the identity pair the receive path
        (57.a.4/57.a.5) needs to persist ``workflow_update`` events and advance
        handle state.

        Args:
            kind (InboxMessageKind): Workflow lifecycle message kind.
            delivery_mode (InboxDeliveryMode): ``context_note`` or ``chat_turn``.
            title (str): Short display title.
            text (str): Primary display or prompt text.
        """
        try:
            await self._store.enqueue(
                message=SessionInboxMessageDAO(
                    session_id=self._target_session_id,
                    schedule_id=f"workflow:{self._workflow_id}",
                    run_id=str(uuid4()),
                    kind=kind,
                    delivery_mode=delivery_mode,
                    priority="normal",
                    title=title,
                    text=text,
                    payload={
                        "workflow_id": self._workflow_id,
                        "orchestrator_session_id": self._orchestrator_session_id,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001 — notify must never kill the workflow
            log_info(msg="workflow_notify_failed", kind=kind, error=str(exc))
