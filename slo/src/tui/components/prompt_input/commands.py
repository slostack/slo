"""Typed presentation deliveries to the prompt editor; binding is a separate operation."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.agents.slo_agent.messaging.dao import _require_uuid
from src.tui.components.prompt_input.submission import (
    DraftSubmissionDAO,
    RetrySubmissionDAO,
    SubmissionOutcomeDAO,
)
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
    """Record admitted human text once per ID within the submission binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str
    message_id: Optional[str] = Field(
        default=None, description="Admission or application identity used to deduplicate human recall."
    )


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


class SubmitDraftDAO(BaseModel):
    """Register one captured draft with the component's submission binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    draft_submission: DraftSubmissionDAO = Field(
        description="Exact captured draft to register before clearing its revision."
    )


class DiscardDraftDAO(BaseModel):
    """Drop one recoverable local snapshot, releasing its reservation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    message_id: str = Field(description="Canonical UUID of the recoverable snapshot to discard.")

    @field_validator("message_id")
    @classmethod
    def _uuid_fields(cls, value: str) -> str:
        return _require_uuid(value=value, field="message_id")


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
    | SubmitDraftDAO
    | SubmissionOutcomeDAO
    | RetrySubmissionDAO
    | DiscardDraftDAO
)
