"""Structural UI delivery contracts; implementations retain native framework ownership."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, TypeVar

from src.tui.components.chat_transcript.commands import ProjectionInput, TranscriptNoticeDAO
from src.tui.components.workflow_progress.events import WorkflowProgressUpdate

if TYPE_CHECKING:
    from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeMountTarget
    from src.tui.components.chat_transcript.adapters.workflow_notice import TranscriptNoticeTarget
    from src.tui.components.chat_transcript.adapters.transcript_projector import TranscriptMountHost
    from src.tui.components.workflow_progress.adapters.workflow_progress import SessionListPresenter
    from src.tui.components.workflow_progress.host import WorkflowProgressHost
    from src.tui.workflows.dao import WorkflowSessionKeyDAO

CommandT = TypeVar("CommandT", contravariant=True)
InputT = TypeVar("InputT", contravariant=True)


class ComponentProtocol(Protocol[CommandT]):
    """UI-loop command receiver with ordered, applied (not painted) completion.

    Implementations reject unsupported inputs with TypeError and closed delivery
    with RuntimeError (closed wins). Errors propagate to the awaiting caller.
    Reset retains borrowed dependencies; close never closes borrowed targets.
    """

    async def handle(self, *, command: CommandT) -> None:
        """Apply a command before returning, preserving admission order.

        Args:
            command: One member of the receiver's declared command union.
        """
        ...

    async def reset(self) -> None:
        """Invalidate stale presentation work and clear transient state for reuse."""
        ...

    async def close(self) -> None:
        """Idempotently seal admission and join owned work without closing dependencies."""
        ...


class AdapterProtocol(Protocol[InputT]):
    """Delivery-only event translation; full registration capabilities follow below.

    Owners admit UI work before delivery. Adapters pin the first delivery/reset
    loop, not the loop on which they were constructed, and borrow their targets.
    """

    async def handle(self, *, event: InputT) -> None:
        """Translate and apply an event, propagating translation/delivery errors.

        Args:
            event: One member of the adapter's declared input union.
        """
        ...

    async def reset(self) -> None:
        """Invalidate stale owned work and clear local state, retaining the target."""
        ...

    async def close(self) -> None:
        """Idempotently retire owned work; the borrowed target remains alive."""
        ...


class TranscriptNoticeDisplayProtocol(AdapterProtocol[TranscriptNoticeDAO], Protocol):
    """Register inert notice display with a borrowed specialized mounting leaf."""

    @classmethod
    def register(cls, *, tui: TranscriptNoticeMountTarget) -> Self:
        """Return a fresh display without mounting, starting tasks or capturing a loop."""
        ...


class WorkflowNoticeProtocol(AdapterProtocol[TranscriptNoticeDAO], Protocol):
    """Register inert workflow notices with a borrowed command admission target."""

    @classmethod
    def register(cls, *, tui: TranscriptNoticeTarget) -> Self:
        """Return a fresh notice lifetime; closing it never closes the destination."""
        ...


class TranscriptProjectionProtocol(AdapterProtocol[ProjectionInput], Protocol):
    """Register live/replay projection without widening the specialized mount host."""

    @classmethod
    def register(cls, *, host: TranscriptMountHost) -> Self:
        """Return a fresh projector without reading history or mounting widgets."""
        ...


class WorkflowProgressUpdatesProtocol(AdapterProtocol[WorkflowProgressUpdate], Protocol):
    """Register progress translation with separate borrowed UI and row capabilities."""

    @classmethod
    def register(cls, *, host: WorkflowProgressHost, presenter: SessionListPresenter) -> Self:
        """Return a fresh inactive sink; its component still owns binding admission."""
        ...

    def open_progress(self, *, key: WorkflowSessionKeyDAO) -> bool:
        """Open/select progress and acknowledge whether the coordinator may observe it."""
        ...
