"""Versioned Slo-owned control-channel messages for the isolated Slotui host.

Terminal stdin/stdout belong exclusively to the candidate adapter.  This module
models only the Unix-domain control socket and never imports Slotui.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.slo_agent.events.stream import AgentStreamEventDAO, StreamEventKind

__all__ = [
    "SLOTUI_HOST_CONTROL_PROTOCOL_VERSION",
    "SlotuiHostCommandDAO",
    "SlotuiHostEventDAO",
    "SlotuiHostLaunchConfigDAO",
    "SlotuiLiveTranscriptMutationDAO",
    "SlotuiStreamEventMapper",
]

SLOTUI_HOST_CONTROL_PROTOCOL_VERSION: Final[Literal["slo-slotui-host-control-v2"]] = (
    "slo-slotui-host-control-v2"
)
SlotuiHostCommandKind = Literal["launch", "stream_event", "session_notice", "session_failed", "shutdown"]
SlotuiHostEventKind = Literal[
    "launch_ack",
    "host_active",
    "editor_submit",
    "host_closed",
    "host_failed",
    "attestation",
    "transcript_ack",
]
SlotuiTranscriptMutationKind = Literal["create", "append", "update", "end", "notice", "failed"]


class SlotuiHostLaunchConfigDAO(BaseModel):
    """Carry resolved Slo launch facts over the control socket."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["slo-slotui-host-control-v2"]
    workdir: str
    resume_session_id: str | None = None
    session_id: str
    control_socket_path: str
    adapter_declaration: str


class SlotuiHostEventDAO(BaseModel):
    """Describe one candidate-adapter lifecycle, editor, or transcript acknowledgement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["slo-slotui-host-control-v2"]
    kind: SlotuiHostEventKind
    prompt: str | None = None
    detail: str | None = None
    adapter_declaration: str | None = None
    terminal_ready: bool | None = None
    root_ready: bool | None = None
    editor_ready: bool | None = None
    transcript_ready: bool | None = None
    imported_module_path: str | None = None
    source_paths_absent: bool | None = None
    mutation_id: str | None = None

    @model_validator(mode="after")
    def _validate_event_fields(self) -> "SlotuiHostEventDAO":
        """Reject fields that do not belong to the declared candidate event.

        Raises:
            ValueError: If a lifecycle event carries fields from another command shape.
        """
        allowed_fields: dict[str, set[str]] = {
            "launch_ack": {"adapter_declaration"},
            "host_active": {
                "adapter_declaration",
                "terminal_ready",
                "root_ready",
                "editor_ready",
                "transcript_ready",
            },
            "editor_submit": {"prompt"},
            "host_closed": {"detail"},
            "host_failed": {"detail"},
            "attestation": {"adapter_declaration", "imported_module_path", "source_paths_absent"},
            "transcript_ack": {"mutation_id"},
        }
        provided_fields: set[str] = {
            field_name
            for field_name in (
                "prompt",
                "detail",
                "adapter_declaration",
                "terminal_ready",
                "root_ready",
                "editor_ready",
                "transcript_ready",
                "imported_module_path",
                "source_paths_absent",
                "mutation_id",
            )
            if getattr(self, field_name) is not None
        }
        if not provided_fields <= allowed_fields[self.kind]:
            raise ValueError(f"Slotui host event fields are invalid for {self.kind}")
        if self.kind == "editor_submit" and (self.prompt is None or not self.prompt.strip()):
            raise ValueError("Slotui editor_submit requires a non-empty prompt")
        if self.kind == "transcript_ack" and self.mutation_id is None:
            raise ValueError("Slotui transcript_ack requires mutation_id")
        return self


class SlotuiLiveTranscriptMutationDAO(BaseModel):
    """Describe one generic mutation while preserving actual Slo event metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SlotuiTranscriptMutationKind
    block_id: str | None = None
    text: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    iteration: int = 0
    content_index: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)


class SlotuiHostCommandDAO(BaseModel):
    """Describe one parent-to-adapter control message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["slo-slotui-host-control-v2"]
    kind: SlotuiHostCommandKind
    launch: SlotuiHostLaunchConfigDAO | None = None
    mutation: SlotuiLiveTranscriptMutationDAO | None = None
    mutation_id: str | None = None
    notice: str | None = None

    @model_validator(mode="after")
    def _validate_command_fields(self) -> "SlotuiHostCommandDAO":
        """Reject command payload fields outside the declared command kind.

        Raises:
            ValueError: If a command has missing or unrelated payload fields.
        """
        payload_by_kind: dict[str, tuple[str, ...]] = {
            "launch": ("launch",),
            "stream_event": ("mutation", "mutation_id"),
            "session_notice": ("notice",),
            "session_failed": ("notice",),
            "shutdown": (),
        }
        provided_fields: set[str] = {
            field_name
            for field_name in ("launch", "mutation", "mutation_id", "notice")
            if getattr(self, field_name) is not None
        }
        required_fields: set[str] = set(payload_by_kind[self.kind])
        if provided_fields != required_fields:
            raise ValueError(f"Slotui host command fields are invalid for {self.kind}")
        return self


class SlotuiStreamEventMapper:
    """Map every canonical Slo stream kind to an explicit generic adapter mutation."""

    @classmethod
    def invoke(cls, *, event: AgentStreamEventDAO) -> SlotuiLiveTranscriptMutationDAO:
        """Map one actual Slo event without silently dropping its identity or metadata.

        Args:
            event (AgentStreamEventDAO): Canonical event emitted by the parent session.

        Returns:
            SlotuiLiveTranscriptMutationDAO: Explicit create/update/end/notice/failure operation.
        """
        mutation_kind: SlotuiTranscriptMutationKind = cls._mutation_kind(event_kind=event.kind)
        text: str = cls._event_text(event=event)
        return SlotuiLiveTranscriptMutationDAO(
            kind=mutation_kind,
            block_id=event.block_id,
            text=text,
            tool_name=event.tool_name,
            tool_call_id=event.tool_call_id,
            iteration=event.iteration,
            content_index=event.content_index,
            metadata={
                "stream_kind": event.kind,
                "tool_input": event.tool_input,
                "tool_arguments_delta": event.tool_arguments_delta,
                "redacted": event.redacted,
                "event_metadata": event.metadata,
                "sub_agent_id": event.sub_agent_id,
                "task_id": event.task_id,
            },
        )

    @staticmethod
    def unsupported_surface_notices() -> tuple[str, ...]:
        """Return honest startup limitations for the candidate transcript.

        Returns:
            tuple[str, ...]: Limitations that cannot be interpreted as parity claims.
        """
        return (
            "Images, LaTex, and Mermaid render as raw/literal content in Slotui.",
            "Slo authentication, /diff, history tree, replay, slash, fleet, and workflow overlays are unavailable in Slotui.",
            "Rapid editor submissions are rejected while one Slo prompt is active; no editor queue is implemented.",
        )

    @staticmethod
    def _mutation_kind(*, event_kind: StreamEventKind) -> SlotuiTranscriptMutationKind:
        """Choose the explicit generic operation for one canonical stream kind.

        Args:
            event_kind (StreamEventKind): Slo event discriminator.

        Returns:
            SlotuiTranscriptMutationKind: Candidate adapter operation with no implicit fallback.
        """
        if event_kind in {"thinking_start", "text_start", "tool_call_start"}:
            return "create"
        if event_kind in {"thinking_delta", "text_delta", "tool_call_delta", "tool_output_update"}:
            return "append"
        if event_kind in {"thinking_end", "text_end", "tool_call_end", "tool_result", "run_completed"}:
            return "end"
        if event_kind in {"run_aborted", "run_failed", "sub_agent_failed", "recovery_exhausted"}:
            return "failed"
        return "notice"

    @staticmethod
    def _event_text(*, event: AgentStreamEventDAO) -> str:
        """Produce literal text for every mapped event.

        Args:
            event (AgentStreamEventDAO): Canonical event to render.

        Returns:
            str: Delta/content when available, otherwise a stable literal event label.
        """
        return event.delta or event.content or event.kind.replace("_", " ")
