"""Typed presentation requests; execution and persistence stay with the app."""

from collections.abc import Awaitable, Callable
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from textual.widget import Widget

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO

HistoryReader = Callable[[], Awaitable[list[TranscriptEntryDAO]]]


class EchoUserDAO(BaseModel):
    """Display already accepted text without submitting or persisting it."""

    model_config = ConfigDict(frozen=True)
    text: str


class PresentAgentEventDAO(BaseModel):
    """Present one normalized parent event."""

    model_config = ConfigDict(frozen=True)
    event: AgentStreamEventDAO


class HydrateTranscriptDAO(BaseModel):
    """Read the bounded history tail before subscribing to live events."""

    model_config = ConfigDict(frozen=True)
    is_current: Optional[Callable[[], bool]] = None


class BindHistoryDAO(BaseModel):
    """Retire the current presentation before adopting borrowed history."""

    model_config = ConfigDict(frozen=True)
    history_reader: HistoryReader


class ClearTranscriptDAO(BaseModel):
    """Clear transient presentation without erasing persisted history."""

    model_config = ConfigDict(frozen=True)


class BeginTranscriptRunDAO(BaseModel):
    """Retire projector identity maps before the next accepted prompt."""

    model_config = ConfigDict(frozen=True)


class LoadOlderHistoryDAO(BaseModel):
    """Read the preceding bounded history page."""

    model_config = ConfigDict(frozen=True)


class ShowPendingSteeringDAO(BaseModel):
    """Display accepted steering while execution owns its queue."""

    model_config = ConfigDict(frozen=True)
    message: str


class MountTreeOutputDAO(BaseModel):
    """Present an exported tree outside ordinary transcript accounting."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    widget: Widget


class SetTranscriptVisibilityDAO(BaseModel):
    """Retain the surface while changing visibility, without focus policy."""

    model_config = ConfigDict(frozen=True)
    visible: bool


class ScrollTranscriptBottomDAO(BaseModel):
    """Resume following the transcript tail."""

    model_config = ConfigDict(frozen=True)


class ToggleTranscriptDetailsDAO(BaseModel):
    """Cycle expansion of ordinary transcript blocks."""

    model_config = ConfigDict(frozen=True)


class TranscriptNoticeDAO(BaseModel):
    """Append one semantic notice in logical order and mount it before returning."""

    model_config = ConfigDict(frozen=True)
    content: str
    classes: str = ""
    before: Optional[int] = None


class SetScrollPositionDAO(BaseModel):
    """Apply owner-selected coordinates immediately, without waiting for paint."""

    model_config = ConfigDict(frozen=True)
    x: Optional[float] = None
    y: Optional[float] = None


class ProjectUserTurnDAO(BaseModel):
    """Project accepted text at the specialized mount-host boundary."""

    model_config = ConfigDict(frozen=True)
    text: str
    before: Optional[int] = None


class ProjectReplayEntryDAO(BaseModel):
    """Project a finalized canonical entry without changing live identities."""

    model_config = ConfigDict(frozen=True)
    entry: TranscriptEntryDAO
    before: Optional[int] = None


class RetireHistoryBindingDAO(BaseModel):
    """Retire application identity only when the canonical history binding changes."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PresentMessageApplicationDAO(BaseModel):
    """Present one verified canonical application through the replay identity owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    entry: TranscriptEntryDAO = Field(
        description="Verified canonical application projected through binding identity deduplication."
    )


ProjectionInput = AgentStreamEventDAO | ProjectUserTurnDAO | ProjectReplayEntryDAO | RetireHistoryBindingDAO


ScrollCommand = SetScrollPositionDAO


TranscriptCommand = (
    EchoUserDAO
    | PresentMessageApplicationDAO
    | PresentAgentEventDAO
    | HydrateTranscriptDAO
    | BindHistoryDAO
    | ClearTranscriptDAO
    | BeginTranscriptRunDAO
    | LoadOlderHistoryDAO
    | ShowPendingSteeringDAO
    | MountTreeOutputDAO
    | SetTranscriptVisibilityDAO
    | ScrollTranscriptBottomDAO
    | ToggleTranscriptDetailsDAO
    | TranscriptNoticeDAO
)
