"""WorkflowNotifier — channel writer for detached workflow lifecycle (108.3 §4; was spec 57.a.3).

Constructed by ``HeadlessRunner`` when ``--notify-session`` is present. The
notifier is the single writer of workflow traffic: ``started`` and per-phase
``phase_update`` ship as ``note`` rows to the owning TUI session's agent
participant, ``fleet_update`` ships as a ``notice`` row under the workflow's
fleet coalesce key, and the terminal ``completed`` / ``failed`` / ``aborted``
messages ship as normal ``prompt`` rows. Every send failure is swallowed and
logged — a workflow must never die because the TUI's queue is unavailable.
"""

from __future__ import annotations

from typing import Optional
from uuid import NAMESPACE_URL, UUID, uuid5

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.auth.credential_resolver import CredentialResolver
from src.channels.dao import NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.agents.slo_agent.orchestrator.status_store import OrchestratorStatusStore

__all__ = ["NS_WORKFLOW", "WorkflowNotifier"]

_BRIEF_PREVIEW_MAX_CHARS: int = 200

NS_WORKFLOW: UUID = uuid5(NAMESPACE_URL, "slo:channels:workflow-notifier")
"""Deterministic namespace for workflow channel message ids (108.3 §4)."""


def _workflow_message_id(*, workflow_id: str, event: str, phase_index: int) -> UUID:
    """Build the deterministic id for one workflow lifecycle message.

    A notifier that retries after a crash rebuilds the same id and hits the
    duplicate-id rule instead of creating a second row (108.3 §4).

    Args:
        workflow_id (str): Owning workflow id.
        event (str): Lifecycle event name, e.g. ``started`` or ``fleet``.
        phase_index (int): Event ordinal: 0 for once-per-run events, 1.. for
            phases and fleet transitions.

    Returns:
        UUID: The message id.
    """
    return uuid5(NS_WORKFLOW, f"{workflow_id}:{event}:{phase_index}")


class WorkflowNotifier:
    """Sends workflow lifecycle messages into the owning session's channel queue.

    Constructed by ``HeadlessRunner`` when ``--notify-session`` is present.
    Every public method is invoked by the runner's event tap at exactly one
    lifecycle boundary. The orchestrator participant is registered lazily on
    the first send so the sender identity never depends on registration order.
    """

    def __init__(
        self,
        *,
        gateway: ChannelGateway,
        target_session_id: str,
        orchestrator_session_id: str,
        workflow_id: str,
        status_store: Optional[OrchestratorStatusStore] = None,
    ) -> None:
        """Bind the notifier to its target session, queue gateway and workflow identity.

        Args:
            gateway (ChannelGateway): The shared channel queue API.
            target_session_id (str): TUI session whose agent participant
                receives the messages.
            orchestrator_session_id (str): This orchestrator's own session id;
                it becomes the ``agent`` sender participant.
            workflow_id (str): Workflow id from ``SLO_WORKFLOW_ID`` (or 'wf-unknown').
            status_store (Optional[OrchestratorStatusStore]): Durable status reader
                used to suppress delayed fleet notices after terminal state.
        """
        self._gateway: ChannelGateway = gateway
        self._target_session_id: str = target_session_id
        self._orchestrator_session_id: str = orchestrator_session_id
        self._workflow_id: str = workflow_id
        self._status_store: Optional[OrchestratorStatusStore] = status_store
        self._sender_id: UUID = channel_participant_id_for_session(session_id=orchestrator_session_id)
        self._recipient_id: UUID = channel_participant_id_for_session(session_id=target_session_id)
        self._sender_registered: bool = False
        self._phase_index: int = 0
        self._fleet_index: int = 0

    async def started(self, *, brief_preview: str) -> None:
        """Send the workflow_started note. Invoked once, pre-first-LLM-call.

        Args:
            brief_preview (str): Leading slice of the workflow brief for display.
        """
        await self._safe_send(
            event="started",
            phase_index=0,
            message_type="note",
            text=(
                f"[workflow {self._workflow_id}] started — orchestrator session "
                f"{self._orchestrator_session_id}. Brief: {brief_preview[:_BRIEF_PREVIEW_MAX_CHARS]}"
            ),
        )

    async def phase_update(self, *, phase_summary: str) -> None:
        """Send one phase-update note. Invoked per spawn_sub_agents result.

        Args:
            phase_summary (str): One-line digest built by the event tap from the
                ``OrchestratorResultDAO`` (task ids, all_completed, failed ids).
        """
        self._phase_index += 1
        await self._safe_send(
            event="phase",
            phase_index=self._phase_index,
            message_type="note",
            text=(f"[workflow {self._workflow_id}] phase {self._phase_index}: {phase_summary}"),
        )

    async def fleet_update(self, *, entries: list[dict[str, object]], live_count: int) -> None:
        """Send one fleet snapshot notice at a sub-agent lifecycle transition.

        The notice is display-only (never enters model context) and carries
        the workflow's fleet coalesce key, so a burst leaves only the newest
        pending row (108.3 §4).

        Args:
            entries (list[dict[str, object]]): Compact child fleet entries.
            live_count (int): Children currently recorded as running.
        """
        if self._is_terminal():
            return
        self._fleet_index += 1
        await self._safe_send(
            event="fleet",
            phase_index=self._fleet_index,
            message_type="notice",
            coalesce_key=f"wf:{self._workflow_id}:fleet",
            text=self._fleet_summary_text(entries=entries, live_count=live_count),
        )

    async def completed(
        self,
        *,
        synthesis: str,
        result_json: str,
        cleanup_summary: str = "",
    ) -> None:
        """Send the terminal normal-prompt synthesis and fleet cleanup summary.

        Args:
            synthesis (str): The orchestrator's final answer text.
            result_json (str): Last ``OrchestratorResultDAO`` JSON (or ``"{}"``).
            cleanup_summary (str): Final fleet accounting line when available.
        """
        await self._safe_send(
            event="completed",
            phase_index=0,
            message_type="prompt",
            text=(
                f"Workflow {self._workflow_id} completed. Present this synthesis to the "
                f"user and be ready for follow-ups.\n\nSynthesis:\n{synthesis}\n\n"
                f"Raw results JSON:\n{result_json}"
                f"{self._cleanup_summary_suffix(cleanup_summary=cleanup_summary)}"
            ),
        )

    async def failed(self, *, error: str, cleanup_summary: str = "") -> None:
        """Send the terminal failure prompt. Invoked for run_failed or any kind neither completed nor aborted.

        Args:
            error (str): Terminal error or state description.
        """
        await self._safe_send(
            event="failed",
            phase_index=0,
            message_type="prompt",
            text=(
                f"Workflow {self._workflow_id} did not complete. Error/state: {error}. "
                f"Summarise for the user; suggest /workflows and the visualizer for detail."
                f"{self._cleanup_summary_suffix(cleanup_summary=cleanup_summary)}"
            ),
        )

    async def aborted(self, *, reason: str, cleanup_summary: str = "") -> None:
        """Send the final abort prompt after the runner reports run_aborted.

        Send failures are logged and swallowed, while cancellation still
        propagates.

        Args:
            reason (str): Terminal abort reason from HeadlessRunner.
            cleanup_summary (str, optional): Final fleet accounting. Defaults to "".
        """
        await self._safe_send(
            event="aborted",
            phase_index=0,
            message_type="prompt",
            text=(
                f"Workflow {self._workflow_id} was aborted. Reason: {reason}. "
                "An aborted workflow is final: do not retry, resume or relaunch it. "
                "Tell the user it was aborted and suggest /workflows for its final state."
                f"{self._cleanup_summary_suffix(cleanup_summary=cleanup_summary)}"
            ),
        )

    def _is_terminal(self) -> bool:
        """Return whether durable orchestrator evidence has reached a terminal state.

        WHAT: Stops delayed fleet progress after a workflow terminal transition.
        WHO: Called by fleet_update before it sends a notice.
        WHEN: On every relayed child lifecycle event.

        Returns:
            bool: True only when the bound durable status is terminal.
        """
        if self._status_store is None:
            return False
        status = self._status_store.load()
        return status is not None and status.state != "running"

    @staticmethod
    def _fleet_summary_text(*, entries: list[dict[str, object]], live_count: int) -> str:
        """Render the compact fleet notice line."""
        active: list[str] = [
            f"{entry.get('task_id', '')} {entry.get('heartbeat_phase') or entry.get('status', '')}"
            for entry in entries
            if entry.get("status") == "running"
        ]
        completed_count: int = sum(1 for entry in entries if entry.get("status") == "completed")
        suffix: str = f" · {completed_count} completed" if completed_count else ""
        return f"fleet: {live_count} live ({', '.join(active)}){suffix}"

    @staticmethod
    def _cleanup_summary_suffix(*, cleanup_summary: str) -> str:
        """Return a newline-prefixed cleanup line when the runner supplied one."""
        return f"\n\n{cleanup_summary}" if cleanup_summary else ""

    async def _ensure_sender(self) -> None:
        """Register this orchestrator's agent participant exactly once.

        The participant id IS the orchestrator session id (overview §2.3);
        the upsert is idempotent, so re-registration from a fresh process is
        safe and keeps the display label ``orchestrator <workflow id>``.
        """
        if self._sender_registered:
            return
        await self._gateway.register_agent(
            session_id=self._sender_id,
            name=f"orchestrator {self._workflow_id}",
        )
        self._sender_registered = True

    async def _safe_send(
        self,
        *,
        event: str,
        phase_index: int,
        message_type: str,
        text: str,
        coalesce_key: Optional[str] = None,
    ) -> None:
        """Build and send one lifecycle row; swallow and log every failure.

        Args:
            event (str): Lifecycle event name baked into the message id.
            phase_index (int): Event ordinal baked into the message id.
            message_type (str): ``note``, ``notice`` or ``prompt`` (108.3 §4).
            text (str): Primary display or prompt text, redacted before send.
            coalesce_key (Optional[str]): Supersede key for ``notice`` rows.
        """
        try:
            safe_text: str = CredentialResolver.redact_openrouter_text(text=text)
            await self._ensure_sender()
            await self._gateway.send(
                new=NewMessageDAO(
                    id=_workflow_message_id(
                        workflow_id=self._workflow_id,
                        event=event,
                        phase_index=phase_index,
                    ),
                    sender_id=self._sender_id,
                    recipient_id=self._recipient_id,
                    message_contents=safe_text,
                    message_type=message_type,  # type: ignore[arg-type]
                    coalesce_key=coalesce_key,
                )
            )
        except Exception as exc:  # noqa: BLE001 — notify must never kill the workflow
            from config.logger import log_info  # noqa: PLC0415

            log_info(msg="workflow_notify_failed", kind=event, error=str(exc))
