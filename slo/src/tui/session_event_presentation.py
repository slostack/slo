"""Translate session status and notices without owning UI or session lifetime."""

from typing import ClassVar

from pydantic import BaseModel

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.tui.components.chat_transcript.commands import TranscriptNoticeDAO


class SessionEventPresentationDAO(BaseModel):
    """Transient copy for the app's existing spinner and transcript destinations."""

    notice: TranscriptNoticeDAO | None = None
    spinner_status: str | None = None
    update_spinner: bool = True
    notice_only: bool = False


class SessionEventPresentation:
    """Own status copy and special notices, not routing, usage or async delivery."""

    _STATUS: ClassVar[dict[str, str]] = {
        "compaction_started": "Compacting session history…",
        "compaction_completed": "Compaction complete.",
        "compaction_retrying": "Retrying original message…",
        "recovery_started": "Recovering from error…",
        "recovery_succeeded": "Recovered — continuing.",
        "recovery_exhausted": "Could not recover automatically.",
    }

    @classmethod
    def build(cls, *, event: AgentStreamEventDAO) -> SessionEventPresentationDAO:
        """Translate one event synchronously before app-owned routing and delivery.

        Args:
            event: Normalized session event; raw reconnect content is not displayed.

        Returns:
            Requested status update and optional special notice. Ordinary events
            retain the existing projector path; no work or resources are retained.
        """
        if event.kind == "run_retrying":
            return SessionEventPresentationDAO(spinner_status=event.content or "Retrying…", notice_only=True)
        if event.kind == "stream_reconnecting":
            return cls._build_reconnect_notice(event=event)
        if event.kind in {"preflight_bypassed", "compaction_advised"}:
            content: str = (
                "(local token preflight bypassed; request sent to provider)"
                if event.kind == "preflight_bypassed"
                else event.content or "Run /compact to help latency."
            )
            return SessionEventPresentationDAO(
                notice=TranscriptNoticeDAO(content=content, classes="tool-result"),
                update_spinner=False,
                notice_only=True,
            )
        status: str | None = cls._STATUS.get(event.kind)
        if event.kind == "compaction_failed":
            status = f"Compaction failed: {event.content}" if event.content else "Compaction failed."
        return SessionEventPresentationDAO(spinner_status=status)

    @classmethod
    def _build_reconnect_notice(cls, *, event: AgentStreamEventDAO) -> SessionEventPresentationDAO:
        """Use only public reconnect reason/family metadata, never raw error text.

        Args:
            event: Session-owned reconnect audit event.

        Returns:
            A notice and status with the established fallback copy.
        """
        reason_code: object = event.metadata.get("reason_code")
        exception_family: object = event.metadata.get("exception_family")
        reason: str = reason_code if isinstance(reason_code, str) else "provider_stream_disconnected"
        family: str = exception_family if isinstance(exception_family, str) else "transport error"
        return SessionEventPresentationDAO(
            notice=TranscriptNoticeDAO(
                content=f"(reconnecting after {reason}: {family})", classes="tool-result"
            ),
            spinner_status="Reconnecting provider stream…",
            notice_only=True,
        )
