"""Typed presentation deliveries to the prompt editor; binding is a separate operation."""

from pydantic import BaseModel, ConfigDict

from src.tui.path_suggestion_controller import PathPromptSnapshotDAO, PathSuggestionController
from src.tui.slash_suggestion_engine import SlashSuggestionStateDAO


class ClearSubmissionDAO(BaseModel):
    """Clear the submitted draft and dismiss suggestions before routing it."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReplacePromptDAO(BaseModel):
    """Replace the draft and place the native cursor at its end."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str


class HideSuggestionsDAO(BaseModel):
    """Dismiss suggestions without changing the draft or recall."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RecordAcceptedPromptDAO(BaseModel):
    """Record an admitted ordinary prompt for local recall."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str


class SetModelContextDAO(BaseModel):
    """Publish the selected session's current model to the picker."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    active_model_name: str


class RecordModelSelectionDAO(BaseModel):
    """Record a changed slash-model selection in picker recency."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    model_name: str


class RefreshPublishedSuggestionsDAO(BaseModel):
    """Reevaluate visible suggestions from the published catalog revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PublishSuggestionsDAO(BaseModel):
    """Deliver path rows only under the captured binding and draft authority."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    state: SlashSuggestionStateDAO
    controller: PathSuggestionController
    snapshot: PathPromptSnapshotDAO


class ReplacePathSpanDAO(BaseModel):
    """Deliver one undo-aware completion edit under captured prompt authority."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    insert_text: str
    start: tuple[int, int]
    end: tuple[int, int]
    cursor_inside_quote: bool
    controller: PathSuggestionController
    snapshot: PathPromptSnapshotDAO


PromptCommand = (
    ClearSubmissionDAO
    | ReplacePromptDAO
    | HideSuggestionsDAO
    | RecordAcceptedPromptDAO
    | SetModelContextDAO
    | RecordModelSelectionDAO
    | RefreshPublishedSuggestionsDAO
    | PublishSuggestionsDAO
    | ReplacePathSpanDAO
)
