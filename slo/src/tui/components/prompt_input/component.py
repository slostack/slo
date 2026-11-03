"""Prompt editor owning local suggestion, recall, draft and model-context state (spec 96.f.2)."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from importlib.resources import files
from uuid import uuid4

from src.agents.slo_agent.messaging.client import SessionMessagingClient
from src.agents.slo_agent.messaging.dao import (
    MessageAddressDAO,
    MessageErrorDAO,
    MessageReceiptDAO,
    MessageSubmissionDAO,
    canonical_submission_bytes,
)
from src.tui.components.prompt_input.adapters.message_submission import MessageSubmissionAdapter
from src.tui.components.prompt_input.commands import (
    ClearSubmissionDAO,
    DiscardDraftDAO,
    PromptCommand,
    ReplacePromptDAO,
    HideSuggestionsDAO,
    RecordAcceptedPromptDAO,
    SetModelContextDAO,
    RecordModelSelectionDAO,
    RefreshPublishedSuggestionsDAO,
    PublishSuggestionsDAO,
    ReplacePathSpanDAO,
    SubmitDraftDAO,
)
from src.tui.components.prompt_input.submission import (
    DraftCapacityError,
    DraftHandoffDAO,
    DraftHandoffAckDAO,
    DraftHandoffError,
    RetainedDraftUsageDAO,
    UnresolvedDraftHost,
    DraftSubmissionDAO,
    RecoverableDraftDAO,
    RetrySubmissionDAO,
    SubmissionOutcomeDAO,
    SubmissionUnavailableError,
)
from typing import ClassVar, Literal, Optional, Sequence

from textual.widgets._text_area import Edit

from textual import events
from textual.message import Message
from textual.document._wrapped_document import WrappedDocument
from textual.document._document_navigator import DocumentNavigator
from textual.widgets.text_area import EditResult
from src.tui.widgets.prompt_document import PromptDocument
from src.tui.path_suggestion_controller import PathSuggestionController
from textual.widgets import TextArea

from src.tui.model_catalog import ModelSuggestionProjection
from src.tui.prompt_history import PromptHistoryNavigator
from src.tui.slash_suggestion_engine import SlashSuggestionEngine, SlashSuggestionStateDAO
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu

__all__ = ["PromptInputComponent"]


@dataclass
class _PendingCapture:
    """Stash one captured draft between build and registration on the UI loop."""

    message_id: str
    raw_text: str
    restorable: bool


@dataclass
class _TrackedDraft:
    """One reserved submission snapshot owned by this component."""

    draft_submission: DraftSubmissionDAO
    raw_text: str
    restorable: bool
    state: Literal["waiting", "recoverable"]
    committed: bool = False
    cleared_revision: Optional[int] = None
    last_error: Optional[MessageErrorDAO] = None
    early_outcome: Optional[MessageReceiptDAO | MessageErrorDAO] = None


class _PromptIntent(Message):
    """Carry the emitting editor prompt_version across Textual's native message queue."""

    def __init__(self) -> None:
        """Leave direct handler calls unbound; posting stamps the actual emitter."""
        super().__init__()
        self.prompt: Optional[PromptInputComponent] = None
        self.prompt_version: Optional[int] = None
        self.draft_revision: Optional[int] = None


class PromptInputComponent(TextArea):
    """Let the user write prompts, browse suggestions, and recall earlier prompts.

    Enter requests submission. Modified Enter keys, such as Shift+Enter,
    insert a newline. Tab, Up, Down, and Escape control suggestions when
    the suggestion menu is visible.

    Keep track of the draft, prompt history navigation, suggestions, and
    model display information. Tell the app when the user wants to submit
    or perform another action. The app owns the suggestion menu and decides
    when to run an agent, save a message, or change the selected model."""

    DEFAULT_CSS: ClassVar[str] = (
        files("src.tui.components.prompt_input").joinpath("css.tcss").read_text(encoding="utf-8")
    )

    def __init__(self) -> None:
        """Construct the prompt input with explicit soft wrapping enabled."""
        super().__init__(soft_wrap=True)
        self._suggestion_navigation_enabled: bool = False
        self._prompt_history_navigation_enabled: bool = False
        self._prompt_history: PromptHistoryNavigator = PromptHistoryNavigator()
        self._setting_prompt_from_history: bool = False
        self._slash_suggestion_state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(visible=False)
        # Use a placeholder until binding reads the catalog. Refresh does nothing
        # before binding, so construction does not read the catalog.
        self._picker_catalog_revision: tuple[int, int] = (0, 0)
        self._suggestion_engine: Optional[SlashSuggestionEngine] = None
        self._suggestion_menu: Optional[SlashSuggestionMenu] = None
        self._active_model_name: str = ""
        # Keep our closed flag separate from Textual’s flag so its message queue can finish.
        self._delivery_closed: bool = False
        self._delivery_closing: bool = False
        self._close_task: Optional[asyncio.Task[None]] = None
        self._reset_task: Optional[asyncio.Task[None]] = None
        self._submission_retirement_task: Optional[asyncio.Task[None]] = None
        self._submission_replacement_task: Optional[asyncio.Task[None]] = None
        self._draft_handoff: Optional[DraftHandoffDAO] = None
        self._dropped_draft_count: int = 0
        self._prompt_version: int = 0
        self._path_controller: Optional[PathSuggestionController] = None
        # Draft submission state (96 revised 01.2): the component owns the draft,
        # its revision, the binding, reservations and recoverable snapshots.
        self._draft_revision: int = 0
        self._submission_adapter: Optional[MessageSubmissionAdapter] = None
        self._submission_address: Optional[MessageAddressDAO] = None
        self._submission_loop: Optional[asyncio.AbstractEventLoop] = None
        self._recorded_message_ids: set[str] = set()
        self._recorded_message_order: deque[str] = deque()
        self._submission_binding_version: int = 0
        self._submission_sealed: bool = False
        self._pending_capture: Optional[_PendingCapture] = None
        self._tracked_drafts: dict[str, _TrackedDraft] = {}

    def _set_document(self, text: str, language: Optional[str]) -> None:
        """Create a prompt document that preserves path characters exactly.

        Keep Textual’s normal wrapping, cursor movement, and edit history. Use its
        normal document setup when a syntax language is requested. Every document
        replacement advances the draft revision, including the base constructor's.
        """
        self._draft_revision = getattr(self, "_draft_revision", -1) + 1
        if language:
            super()._set_document(text=text, language=language)
            return
        self._highlight_query = None
        self.document = PromptDocument(text=text)
        self.wrapped_document = WrappedDocument(self.document, tab_width=self.indent_width)
        self.navigator = DocumentNavigator(self.wrapped_document)
        self._build_highlight_map()
        self.move_cursor(location=(0, 0))
        self._rewrap_and_refresh_virtual_size()

    class Edited(_PromptIntent):
        """Notify the application of buffer or selection changes, without exposing state."""

    class PathSuggestionsRequested(_PromptIntent):
        """Request explicit path discovery for the current cursor."""

    class Submitted(_PromptIntent):
        """Posted when the user presses Enter to submit the buffer."""

        def __init__(self, *, text: str) -> None:
            """Carry the submitted text.

            Args:
                text (str): The full multi-line buffer at submit time.
            """
            self.text: str = text
            super().__init__()

    class SuggestionAccepted(_PromptIntent):
        """Posted when the prompt accepts the highlighted suggestion."""

    class SuggestionMoved(_PromptIntent):
        """Posted when the prompt moves the highlighted suggestion row."""

        def __init__(self, *, delta: int) -> None:
            """Carry the row movement request.

            Args:
                delta (int): Positive or negative row movement.
            """
            self.delta: int = delta
            super().__init__()

    class SuggestionDismissed(_PromptIntent):
        """Posted when the prompt dismisses slash suggestions."""

    class PromptHistoryOlderRequested(_PromptIntent):
        """Posted when the prompt requests the next older prompt."""

    class PromptHistoryNewerRequested(_PromptIntent):
        """Posted when the prompt requests the next newer prompt."""

    class SubmissionFeedback(Message):
        """Notify the host of one settled draft outcome."""

        def __init__(
            self, *, message_id: str, error_code: Optional[str], restored: bool, dropped: bool = False
        ) -> None:
            """Carry the fixed outcome fields for host rendering.

            Args:
                message_id (str): The settled draft's canonical ID.
                error_code (Optional[str]): The fixed refusal code, if any.
                restored (bool): Whether the editor took the draft's text back.
            """
            self.message_id: str = message_id
            self.error_code: Optional[str] = error_code
            self.restored: bool = restored
            self.dropped: bool = dropped
            super().__init__()

    def post_message(self, message: Message) -> bool:
        """Mark outgoing prompt messages with the current editor state before Textual queues them."""
        if isinstance(message, _PromptIntent) and message.prompt_version is None:
            message.prompt = self
            message.prompt_version = self._get_prompt_version()
            message.draft_revision = self._draft_revision
        return super().post_message(message)

    def is_prompt_intent_current(self, *, event: _PromptIntent) -> bool:
        """Check whether a queued prompt action still belongs to the current editor state."""
        return self.is_prompt_input_open and (
            event.prompt_version is None
            or (event.prompt is self and event.prompt_version == self._prompt_version)
        )

    @property
    def is_prompt_input_open(self) -> bool:
        """Check whether this mounted editor can still accept keyboard and selection events."""
        return self.is_mounted and not self._delivery_closed and not self._delivery_closing

    @property
    def _is_suggestion_binding_present(self) -> bool:
        """Check that both the suggestion engine and menu are available."""
        return self._suggestion_engine is not None and self._suggestion_menu is not None

    async def bind_suggestions(
        self,
        *,
        menu: SlashSuggestionMenu,
        engine: SlashSuggestionEngine,
        active_model_name: str,
        path_controller: Optional[PathSuggestionController] = None,
    ) -> None:
        """Connect the supplied menu and engine, then update suggestions for the current draft.

        Require a mounted editor and menu with no existing binding. If suggestion
        evaluation fails, release the references and report the original error.
        """
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._ensure_prompt_ui_loop()
        if not menu.is_mounted:
            raise RuntimeError("PromptInputComponent is not mounted")
        if self._is_suggestion_binding_present:
            raise RuntimeError("PromptInputComponent suggestions are already bound")
        # Read the catalog version before saving dependencies so a read failure cannot
        # leave the editor connected to only some of its dependencies.
        catalog_revision = ModelSuggestionProjection.current_revision()
        self._create_suggestion_binding(
            menu=menu,
            engine=engine,
            active_model_name=active_model_name,
            catalog_revision=catalog_revision,
        )
        self._path_controller = path_controller
        prompt_version = self._get_prompt_version()
        try:
            await self._refresh_slash_suggestions()
        except BaseException:
            if self._is_prompt_version(expected_version=prompt_version):
                self._release_failed_binding()
            raise

    def _create_suggestion_binding(
        self,
        *,
        menu: SlashSuggestionMenu,
        engine: SlashSuggestionEngine,
        active_model_name: str,
        catalog_revision: tuple[int, int],
    ) -> None:
        """Save the supplied suggestion menu, engine, and model information."""
        self._suggestion_engine = engine
        self._suggestion_menu = menu
        self._active_model_name = active_model_name
        self._picker_catalog_revision = catalog_revision

    def _release_failed_binding(self) -> None:
        """Try to hide the menu and release a failed binding without hiding the original error.

        The caller checks that the failed binding is still current before calling this method.
        """
        try:
            self._retire_suggestion_binding()
        except Exception:
            # References are already released; report the original binding error.
            pass

    async def _hide_suggestions(self) -> None:
        """Hide suggestions without changing the draft, cursor, prompt history, or recent choices."""
        if self._delivery_closed:
            return
        if self._path_controller is not None:
            await self._path_controller.dismiss()
            return
        hidden_state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(visible=False)
        self._slash_suggestion_state = hidden_state
        self._render_slash_suggestion_state(state=hidden_state)

    def _ensure_prompt_open(self) -> None:
        """Reject closed editor commands before mount or event-loop checks."""
        if self._delivery_closed or self._delivery_closing:
            raise RuntimeError("PromptInputComponent is closed")

    def _ensure_prompt_mounted(self) -> None:
        """Require native mounting before accessing the editor's application."""
        if not self.is_mounted:
            raise RuntimeError("PromptInputComponent requires its mounted UI loop")

    def _ensure_prompt_ui_loop(self) -> None:
        """Raise RuntimeError for mutation attempted outside the mounted UI loop."""
        if asyncio.get_running_loop() is not self.app._loop:
            raise RuntimeError("PromptInputComponent requires its mounted UI loop")

    def edit(self, edit: "Edit") -> EditResult:  # noqa: F821
        """Advance the draft revision at every real edit boundary, then delegate.

        Args:
            edit (Edit): The native Textual edit being applied.

        Returns:
            EditResult: The native result, unchanged.
        """
        self._draft_revision = getattr(self, "_draft_revision", -1) + 1
        return super().edit(edit)

    def _undo_batch(self, edits: "Sequence[Edit]") -> None:  # noqa: F821
        """Advance the draft revision for the whole undo, then delegate.

        Args:
            edits (Sequence[Edit]): The native undo batch.
        """
        self._draft_revision += 1
        super()._undo_batch(edits)

    def _redo_batch(self, edits: "Sequence[Edit]") -> None:  # noqa: F821
        """Advance the draft revision for the whole redo, then delegate.

        Args:
            edits (Sequence[Edit]): The native redo batch.
        """
        self._draft_revision += 1
        super()._redo_batch(edits)

    async def handle(self, *, command: PromptCommand) -> None:
        """Apply a supported editor command on the UI loop without waiting for the screen to repaint.

        Finish text edits and menu updates directly. Await controller callbacks
        without starting another task or acquiring a lock twice. The app still owns
        filesystem reads. Reject unknown commands and calls after close.

        Outcome deliveries are adopted before the mounted check so a settling
        draft is never abandoned during close.
        """
        if isinstance(command, SubmissionOutcomeDAO):
            await self._adopt_submission_outcome(command=command)
            return
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._ensure_prompt_ui_loop()
        if isinstance(command, SubmitDraftDAO):
            await self._handle_draft_submission(command=command)
        elif isinstance(command, RetrySubmissionDAO):
            await self._handle_submission_retry(command=command)
        elif isinstance(command, DiscardDraftDAO):
            self._discard_recoverable_draft(command=command)
        elif isinstance(command, ClearSubmissionDAO):
            self.load_text("")
            await self._hide_suggestions()
        elif isinstance(command, ReplacePromptDAO):
            self.load_text(command.text)
            self._move_cursor_to_end()
        elif isinstance(command, HideSuggestionsDAO):
            await self._hide_suggestions()
        elif isinstance(command, RecordAcceptedPromptDAO):
            self._record_accepted_message(text=command.text, message_id=command.message_id)
        elif isinstance(command, SetModelContextDAO):
            await self._update_model_context(active_model_name=command.active_model_name)
        elif isinstance(command, RecordModelSelectionDAO):
            self._record_model_selection(model_name=command.model_name)
        elif isinstance(command, RefreshPublishedSuggestionsDAO):
            await self._refresh_published_suggestions()
        elif isinstance(command, PublishSuggestionsDAO):
            if self._is_path_delivery_current(command=command):
                self._slash_suggestion_state = command.state
                self._render_slash_suggestion_state(state=command.state)
        elif isinstance(command, ReplacePathSpanDAO):
            if self._is_path_delivery_current(command=command):
                self._replace_path_span(command=command)
        else:
            raise TypeError("Unsupported prompt command")

    async def reset(self) -> None:
        """Clear the draft and recalled prompts, cancel old suggestions, and keep the current dependencies."""
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._ensure_prompt_ui_loop()
        if self._reset_task is None or self._reset_task.done():
            self._update_prompt_version()
            self._reset_task = asyncio.create_task(coro=self._reset_owned())
        await self._join_lifecycle_task(task=self._reset_task)

    async def _reset_owned(self) -> None:
        """Clear before joining outcomes; cancellation cannot skip the adapter barrier."""
        await self._reset_session()
        if self._submission_adapter is not None:
            await self._submission_adapter.reset()

    def _record_accepted_prompt(self, *, text: str) -> None:
        """Add an accepted non-slash prompt to the local prompt history."""
        if self._delivery_closed:
            return
        self._prompt_history.record(text=text)

    async def _update_model_context(self, *, active_model_name: str) -> None:
        """Save the current model name and refresh the model picker if it is visible."""
        if self._delivery_closed or not self._is_suggestion_binding_present:
            # Ignore model updates before binding; binding supplies the initial model.
            return
        self._active_model_name = active_model_name
        if self._slash_suggestion_state.visible:
            await self._refresh_slash_suggestions()

    def _record_model_selection(self, *, model_name: str) -> None:
        """Remember the recently selected model for suggestion ordering."""
        if self._delivery_closed or not self._is_suggestion_binding_present:
            return
        assert self._suggestion_engine is not None
        self._suggestion_engine.record_selection(model_name=model_name)

    async def _refresh_published_suggestions(self) -> None:
        """Refresh the visible picker if the available model catalog changed."""
        if self._delivery_closed or not self._is_suggestion_binding_present:
            return
        if not self._slash_suggestion_state.visible or self._slash_suggestion_state.kind != "slash":
            return
        if ModelSuggestionProjection.current_revision() == self._picker_catalog_revision:
            return
        await self._refresh_slash_suggestions()

    async def _reset_session(self) -> None:
        """Clear recalled prompts, hide suggestions, and empty the draft for the new session."""
        if self._delivery_closed:
            return
        self._prompt_history = PromptHistoryNavigator()
        self._setting_prompt_from_history = False
        self._prompt_history_navigation_enabled = False
        self.load_text("")
        # Clear the draft before dismissing suggestions, so a later session can reuse the same path.
        await self._hide_suggestions()

    async def _on_key(self, event: events.Key) -> None:
        """Handle Enter as submission or a newline, and route suggestion and history keys."""
        if self._delivery_closed or self._delivery_closing:
            event.prevent_default()
            event.stop()
            return
        if self._is_suggestion_acceptance_requested(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionAccepted())
            return
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.post_message(self.PathSuggestionsRequested())
            return
        if self._is_suggestion_movement_requested(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionMoved(delta=self._suggestion_delta(event=event)))
            return
        if self._is_older_prompt_requested(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.PromptHistoryOlderRequested())
            return
        if self._is_newer_prompt_requested(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.PromptHistoryNewerRequested())
            return
        if self._is_suggestion_dismissal_requested(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionDismissed())
            return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(text=self.text))
            return
        if event.key in {"shift+enter", "ctrl+enter", "meta+enter"}:
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)

    def _is_suggestion_acceptance_requested(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should accept a suggestion.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the suggestion menu should accept the current row.
        """
        return self._suggestion_navigation_enabled and event.key == "tab"

    def _is_suggestion_movement_requested(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should move the highlight.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the highlighted suggestion should move.
        """
        return self._suggestion_navigation_enabled and event.key in {"up", "down"}

    def _is_older_prompt_requested(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should request older prompt recall.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when history recall should move older.
        """
        return (
            not self._suggestion_navigation_enabled
            and event.key == "up"
            and (not self.text or self._prompt_history_navigation_enabled)
        )

    def _is_newer_prompt_requested(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should request newer prompt recall.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when history recall should move newer.
        """
        return (
            not self._suggestion_navigation_enabled
            and event.key == "down"
            and self._prompt_history_navigation_enabled
        )

    def _is_suggestion_dismissal_requested(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should dismiss suggestions.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the suggestion menu should close.
        """
        return event.key == "escape"

    @staticmethod
    def _suggestion_delta(*, event: events.Key) -> int:
        """Return the row movement implied by ``event``.

        Args:
            event (events.Key): Up/down key event.

        Returns:
            int: ``1`` for down and ``-1`` for up.
        """
        if event.key == "down":
            return 1
        return -1

    async def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Refresh suggestions when this editor’s text changes."""
        if event.text_area is not self:
            return
        event.stop()
        if self._delivery_closed or self._delivery_closing:
            return
        self.post_message(self.Edited())
        if self._setting_prompt_from_history:
            self._setting_prompt_from_history = False
        elif self._prompt_history.is_navigating:
            self._prompt_history.clear_navigation()
            self._prompt_history_navigation_enabled = False
        await self._refresh_slash_suggestions()

    def on_prompt_input_component_suggestion_moved(
        self, event: "PromptInputComponent.SuggestionMoved"
    ) -> None:
        """Move the highlighted slash suggestion row.

        Args:
            event (PromptInputComponent.SuggestionMoved): Requested row movement.
        """
        event.stop()
        if not self.is_prompt_intent_current(event=event) or not self._is_suggestion_binding_present:
            return
        if not self._slash_suggestion_state.visible:
            return
        self._slash_suggestion_state = self._slash_suggestion_state.with_highlight_delta(delta=event.delta)
        self._render_slash_suggestion_state(state=self._slash_suggestion_state)

    async def on_prompt_input_component_suggestion_dismissed(
        self, event: "PromptInputComponent.SuggestionDismissed"
    ) -> None:
        """Dismiss visible slash suggestions.

        Args:
            event (PromptInputComponent.SuggestionDismissed): Dismissal request.
        """
        event.stop()
        if not self.is_prompt_intent_current(event=event) or not self._is_suggestion_binding_present:
            return
        await self._hide_suggestions()

    async def on_prompt_input_component_suggestion_accepted(
        self, event: "PromptInputComponent.SuggestionAccepted"
    ) -> None:
        """Accept the highlighted slash suggestion when visible.

        Args:
            event (PromptInputComponent.SuggestionAccepted): Acceptance request.
        """
        event.stop()
        if not self.is_prompt_intent_current(event=event) or not self._is_suggestion_binding_present:
            return
        row = self._slash_suggestion_state.highlighted_row
        if row is None:
            return
        if self._slash_suggestion_state.kind == "path" and self._path_controller is not None:
            await self._path_controller.accept(insert_text=row.insert_text)
            return
        updated_text: str = self._build_suggested_prompt_text(
            insert_text=row.insert_text,
            state=self._slash_suggestion_state,
        )
        self.load_text(updated_text)
        self._move_cursor_to_end()
        await self._refresh_slash_suggestions()

    def on_prompt_input_component_prompt_history_older_requested(
        self,
        event: "PromptInputComponent.PromptHistoryOlderRequested",
    ) -> None:
        """Load the next older prompt into the editor when available.

        Args:
            event (PromptInputComponent.PromptHistoryOlderRequested): History request.
        """
        event.stop()
        if not self.is_prompt_intent_current(event=event):
            return
        recalled_text: Optional[str] = self._prompt_history.older(current_buffer=self.text)
        if recalled_text is None:
            return
        self._load_prompt_history_text(text=recalled_text)

    def on_prompt_input_component_prompt_history_newer_requested(
        self,
        event: "PromptInputComponent.PromptHistoryNewerRequested",
    ) -> None:
        """Load the next newer prompt into the editor when available.

        Args:
            event (PromptInputComponent.PromptHistoryNewerRequested): History request.
        """
        event.stop()
        if not self.is_prompt_intent_current(event=event):
            return
        recalled_text: Optional[str] = self._prompt_history.newer()
        if recalled_text is None:
            return
        self._load_prompt_history_text(text=recalled_text)

    async def on_unmount(self) -> None:
        """Use the normal close cleanup when Textual removes the editor."""
        await self.close()

    async def close(self) -> None:
        """Join one irreversible retirement before releasing borrowed references.

        Every caller shares the close barrier through repeated cancellation.
        Outcomes remain deliverable until joins and handoff finish; editor
        commands are refused immediately. The app owns clients, sessions and
        path-controller filesystem work.
        """
        if self.is_mounted and asyncio.get_running_loop() is not self.app._loop:
            raise RuntimeError("PromptInputComponent requires its mounted UI loop")
        if self._delivery_closed:
            return
        self._delivery_closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(coro=self._close_owned())
        await self._join_lifecycle_task(task=self._close_task)

    async def _close_owned(self) -> None:
        """Retire before sealing delivery; forced failure reports lost memory drafts."""
        try:
            await self._join_prior_prompt_operations()
            await self.retire_submission_binding()
        except DraftHandoffError:
            self._dropped_draft_count = len(self._tracked_drafts)
            try:
                if self._submission_adapter is not None:
                    await self._submission_adapter.close()
            finally:
                self._tracked_drafts.clear()
                self._release_submission_binding()
                self.post_message(
                    self.SubmissionFeedback(message_id="", error_code=None, restored=False, dropped=True)
                )
        finally:
            self._delivery_closed = True
            self._retire_suggestion_binding()

    async def _join_prior_prompt_operations(self) -> None:
        """Join reset/rebind barriers before close, without replaying historical failures."""
        for task in (self._submission_replacement_task, self._reset_task):
            if task is None:
                continue
            try:
                await self._join_lifecycle_task(task=task)
            except Exception:
                # Each public caller observes its own result. Retirement below
                # still owns the current binding and must not skip its cleanup.
                continue

    @staticmethod
    async def _join_lifecycle_task(*, task: asyncio.Task[None]) -> None:
        """Join an owned barrier through repeated cancellation, then propagate it.

        Args:
            task (asyncio.Task[None]): The single retained lifecycle operation.
        """
        cancelled: bool = False
        while not task.done():
            try:
                await asyncio.shield(arg=task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def retire_submission_binding(self) -> None:
        """Seal and join the old binding, transferring drafts only on exact acknowledgement.

        Called by replacement, close and (DC06) predecessor retirement. Borrowed
        client/session lifetime is unchanged. Refusal leaves the same adapter
        usable; a subsequent attempt retries the identical handoff key/content.

        Raises:
            DraftHandoffError: The host could not acknowledge every snapshot.
        """
        if self._submission_loop is not None and asyncio.get_running_loop() is not self._submission_loop:
            raise RuntimeError("PromptInputComponent requires its submission loop")
        if self._submission_retirement_task is None:
            if self._submission_adapter is None:
                return
            self._submission_sealed = True
            old_version: int = self._submission_binding_version
            self._submission_binding_version += 1
            self._submission_retirement_task = asyncio.create_task(
                coro=self._retire_submission_owned(old_version=old_version)
            )
        task: asyncio.Task[None] = self._submission_retirement_task
        try:
            await self._join_lifecycle_task(task=task)
        finally:
            # A failed acknowledged transfer can be retried; concurrent callers
            # still observe their captured barrier rather than starting another.
            if task.done() and self._submission_retirement_task is task:
                self._submission_retirement_task = None

    async def _retire_submission_owned(self, *, old_version: int) -> None:
        """Join all receiver work before capturing the exact unresolved handoff."""
        adapter = self._submission_adapter
        assert adapter is not None
        try:
            await self._join_submission_outcomes(adapter=adapter)
            await self._handoff_unresolved_drafts(old_version=old_version)
        except BaseException:
            self._submission_sealed = False
            raise
        try:
            await adapter.close()
        finally:
            self._release_submission_binding()

    async def _join_submission_outcomes(self, *, adapter: MessageSubmissionAdapter) -> None:
        """Join every receiver task, keeping failed deliveries recoverable for forced close.

        Args:
            adapter (MessageSubmissionAdapter): The current component-owned borrower.

        Raises:
            DraftHandoffError: Unexpected delivery failure after all siblings joined.
        """
        try:
            await adapter.reset()
        except Exception as error:
            for entry in self._tracked_drafts.values():
                entry.state = "recoverable"
            raise DraftHandoffError() from error

    async def _handoff_unresolved_drafts(self, *, old_version: int) -> None:
        """Keep ownership on refusal, malformed acknowledgement or uncertain delivery."""
        unresolved = tuple(entry.draft_submission for entry in self._tracked_drafts.values())
        if not unresolved:
            return
        try:
            host = self.app
            if not isinstance(host, UnresolvedDraftHost):
                raise DraftHandoffError()
            assert self._submission_address is not None
            if self._draft_handoff is None or self._draft_handoff.drafts != unresolved:
                self._draft_handoff = DraftHandoffDAO(
                    handoff_id=str(uuid4()),
                    target=self._submission_address,
                    binding_version=old_version,
                    drafts=unresolved,
                )
            handoff = self._draft_handoff
            ack = await host.retain_unresolved_drafts(handoff=handoff)
            if (
                not isinstance(ack, DraftHandoffAckDAO)
                or not ack.accepted
                or ack.handoff_id != handoff.handoff_id
            ):
                raise DraftHandoffError()
        except Exception as error:
            raise DraftHandoffError() from error
        for draft in unresolved:
            self._tracked_drafts.pop(draft.message_submission.message_id, None)
        self._draft_handoff = None

    def _release_submission_binding(self) -> None:
        """Release borrowed references and binding-local recall identity last."""
        self._submission_adapter = None
        self._submission_address = None
        self._submission_loop = None
        self._pending_capture = None
        self._draft_handoff = None
        self._recorded_message_ids.clear()
        self._recorded_message_order.clear()

    def _retire_suggestion_binding(self) -> None:
        """Invalidate queued input and path results before releasing the old suggestion binding."""
        self._update_prompt_version()
        try:
            if self._path_controller is not None:
                self._path_controller.invalidate()
        finally:
            try:
                if self._suggestion_menu is not None and self._suggestion_menu.is_attached:
                    self._suggestion_menu.update_state(state=SlashSuggestionStateDAO(visible=False))
            finally:
                self._suggestion_navigation_enabled = False
                self._prompt_history_navigation_enabled = False
                self._setting_prompt_from_history = False
                self._slash_suggestion_state = SlashSuggestionStateDAO(visible=False)
                self._path_controller = None
                self._suggestion_engine = None
                self._suggestion_menu = None
                self._active_model_name = ""
                self._picker_catalog_revision = (0, 0)

    async def replace_suggestion_binding(
        self,
        *,
        menu: SlashSuggestionMenu,
        engine: SlashSuggestionEngine,
        active_model_name: str,
        path_controller: Optional[PathSuggestionController] = None,
    ) -> None:
        """Disconnect the old suggestion tools before connecting the replacements.

        Do not close the supplied menu or path controller; the app owns them.
        If cleanup or evaluation fails, report the error without installing a
        partial replacement. Require the mounted UI loop and an open editor.
        """
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._ensure_prompt_ui_loop()
        if not menu.is_mounted:
            raise RuntimeError("PromptInputComponent menu is not mounted")
        self._retire_suggestion_binding()
        await self.bind_suggestions(
            menu=menu,
            engine=engine,
            active_model_name=active_model_name,
            path_controller=path_controller,
        )

    async def replace_submission_binding(
        self, *, client: SessionMessagingClient, address: MessageAddressDAO
    ) -> None:
        """Register the component-owned admission adapter for the bound session route.

        WHO: ``SloTUI`` calls it from the messaging activation hook.
        WHEN: After readiness, and only after any predecessor binding has
            joined and handed unresolved snapshots to the host.

        Args:
            client (SessionMessagingClient): Borrowed app-owned session route.
            address (MessageAddressDAO): The session's published incarnation.

        Raises:
            RuntimeError: The editor is closed, unmounted, or off-loop.
            DraftHandoffError: The old binding's drafts could not be retained.
        """
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._ensure_prompt_ui_loop()
        if self._submission_replacement_task is None or self._submission_replacement_task.done():
            self._submission_replacement_task = asyncio.create_task(
                coro=self._replace_submission_owned(client=client, address=address)
            )
        await self._join_lifecycle_task(task=self._submission_replacement_task)

    async def _replace_submission_owned(
        self, *, client: SessionMessagingClient, address: MessageAddressDAO
    ) -> None:
        """Retire then register once; cancelled callers cannot publish a partial binding.

        Args:
            client (SessionMessagingClient): Borrowed successor client.
            address (MessageAddressDAO): Successor recipient incarnation.
        """
        if self._submission_adapter is not None:
            await self.retire_submission_binding()
        if self._delivery_closing:
            return
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._submission_binding_version += 1
        self._recorded_message_ids.clear()
        self._recorded_message_order.clear()
        self._submission_adapter = MessageSubmissionAdapter.register(client=client, receiver=self)
        self._submission_address = address
        self._submission_loop = asyncio.get_running_loop()
        self._submission_sealed = False

    def build_draft_submission(
        self, *, text: str, intent_revision: Optional[int]
    ) -> Optional[DraftSubmissionDAO]:
        """Capture the exact current draft and allocate its canonical ID, synchronously.

        WHO: ``SloTUI.on_prompt_input_component_submitted`` (or slash routing for
            ``/steer``) calls it immediately before ``handle(command=SubmitDraftDAO)``.
        WHEN: On the UI loop, with no suspension before the registration command.

        Args:
            text (str): Host-normalized draft text.
            intent_revision (Optional[int]): Revision stamped at Enter; ``None``
                for slash-originated drafts, which are never auto-restored.

        Returns:
            Optional[DraftSubmissionDAO]: The exact snapshot, or ``None`` when the
                intent is stale because the user edited after Enter.

        Raises:
            SubmissionUnavailableError: No binding exists or the binding is sealed.
            ValueError: The submission exceeds the 64 KiB canonical limit.
        """
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._ensure_prompt_ui_loop()
        if self._submission_adapter is None or self._submission_sealed:
            raise SubmissionUnavailableError()
        if intent_revision is not None and intent_revision != self._draft_revision:
            return None
        assert self._submission_address is not None
        message_submission: MessageSubmissionDAO = MessageSubmissionDAO(
            message_id=str(uuid4()),
            target=self._submission_address,
            kind="agent_input",
            text=text,
        )
        self._pending_capture = _PendingCapture(
            message_id=message_submission.message_id,
            raw_text=self.text,
            restorable=intent_revision is not None,
        )
        return DraftSubmissionDAO(
            message_submission=message_submission,
            draft_revision=self._draft_revision,
            binding_version=self._submission_binding_version,
        )

    async def _handle_draft_submission(self, *, command: SubmitDraftDAO) -> None:
        """Reserve capacity, register one bounded wait, then clear the captured revision.

        Every step before the clear commit runs without suspension on the UI loop,
        so capture, reservation and clear are one atomic section. A failure before
        the commit leaves the editor text untouched.

        Args:
            command (SubmitDraftDAO): The captured snapshot from ``build_draft_submission``.

        Raises:
            RuntimeError: The stash is missing, stale or from another binding.
            DraftCapacityError: A bounded waiting or byte budget is exhausted.
        """
        draft: DraftSubmissionDAO = command.draft_submission
        capture: Optional[_PendingCapture] = self._pending_capture
        self._pending_capture = None
        if (
            capture is None
            or capture.message_id != draft.message_submission.message_id
            or draft.binding_version != self._submission_binding_version
            or self._submission_sealed
            or self._submission_adapter is None
            or (capture.restorable and draft.draft_revision != self._draft_revision)
        ):
            raise RuntimeError("Stale draft submission")
        self._ensure_submission_capacity(
            submission_bytes=len(canonical_submission_bytes(submission=draft.message_submission))
        )
        entry: _TrackedDraft = _TrackedDraft(
            draft_submission=draft,
            raw_text=capture.raw_text,
            restorable=capture.restorable,
            state="waiting",
        )
        self._tracked_drafts[draft.message_submission.message_id] = entry
        try:
            await self._submission_adapter.handle(event=draft)
        except BaseException:
            del self._tracked_drafts[draft.message_submission.message_id]
            raise
        if capture.restorable:
            self.load_text("")
            entry.cleared_revision = self._draft_revision
        entry.committed = True
        if entry.early_outcome is not None:
            self._adopt_tracked_outcome(
                message_id=draft.message_submission.message_id, outcome=entry.early_outcome
            )
        await self._hide_suggestions()

    def _ensure_submission_capacity(self, *, submission_bytes: int) -> None:
        """Refuse one more tracked draft when a bounded reservation budget is full.

        Args:
            submission_bytes (int): Canonical byte cost of the candidate snapshot.

        Raises:
            DraftCapacityError: Four waits, sixteen snapshots or 1 MiB is exhausted.
        """
        waiting: int = sum(1 for entry in self._tracked_drafts.values() if entry.state == "waiting")
        if waiting >= 4:
            raise DraftCapacityError(reason="in_flight")
        host = self.app
        usage: RetainedDraftUsageDAO = (
            host.count_retained_drafts()
            if isinstance(host, UnresolvedDraftHost)
            else RetainedDraftUsageDAO(draft_count=0, canonical_bytes=0)
        )
        if len(self._tracked_drafts) + usage.draft_count >= 16:
            raise DraftCapacityError(reason="recoverable")
        retained_bytes: int = sum(
            len(canonical_submission_bytes(submission=entry.draft_submission.message_submission))
            for entry in self._tracked_drafts.values()
        )
        if retained_bytes + usage.canonical_bytes + submission_bytes > 1_048_576:
            raise DraftCapacityError(reason="recoverable")

    async def _adopt_submission_outcome(self, *, command: SubmissionOutcomeDAO) -> None:
        """Adopt one validated recipient answer for a tracked draft.

        Outcomes are accepted even while the editor is closing so a settling
        draft is never abandoned; the running loop must still be the bound loop.

        Args:
            command (SubmissionOutcomeDAO): The adapter-delivered recipient answer.

        Raises:
            RuntimeError: The editor is closed or a foreign loop delivered.
        """
        if self._delivery_closed:
            raise RuntimeError("PromptInputComponent is closed")
        if self._submission_loop is not None and asyncio.get_running_loop() is not self._submission_loop:
            raise RuntimeError("PromptInputComponent requires its submission loop")
        message_id: str = command.draft_submission.message_submission.message_id
        entry: Optional[_TrackedDraft] = self._tracked_drafts.get(message_id)
        if entry is None:
            return
        if not entry.committed:
            entry.early_outcome = command.outcome
            return
        self._adopt_tracked_outcome(message_id=message_id, outcome=command.outcome)

    def _adopt_tracked_outcome(
        self, *, message_id: str, outcome: MessageReceiptDAO | MessageErrorDAO
    ) -> None:
        """Settle one committed draft: receipts release; errors restore or retain.

        Args:
            message_id (str): The tracked draft's canonical ID.
            outcome (MessageReceiptDAO | MessageErrorDAO): The recipient's answer.
        """
        entry: Optional[_TrackedDraft] = self._tracked_drafts.get(message_id)
        if entry is None:
            return
        if isinstance(outcome, MessageReceiptDAO):
            del self._tracked_drafts[message_id]
            self._record_accepted_message(
                text=entry.draft_submission.message_submission.text, message_id=message_id
            )
            self._post_submission_feedback(message_id=message_id, error_code=None, restored=False)
            return
        entry.state = "recoverable"
        entry.last_error = outcome
        restored: bool = False
        if self._outcome_may_restore(entry=entry, outcome=outcome):
            self.load_text(entry.raw_text)
            self._move_cursor_to_end()
            del self._tracked_drafts[message_id]
            restored = True
        self._post_submission_feedback(message_id=message_id, error_code=outcome.code, restored=restored)

    def _outcome_may_restore(self, *, entry: _TrackedDraft, outcome: MessageErrorDAO) -> bool:
        """Decide restoration only for a rejected draft whose editor stayed cleared.

        Args:
            entry (_TrackedDraft): The tracked snapshot under consideration.
            outcome (MessageErrorDAO): The recipient's refusal.

        Returns:
            bool: Whether the editor may take the draft's text back.
        """
        if outcome.code in ("unknown_outcome", "storage_unavailable", "not_found", "replay_gap"):
            return False
        return (
            entry.restorable
            and not self._submission_sealed
            and not self._delivery_closed
            and not self._delivery_closing
            and entry.draft_submission.binding_version == self._submission_binding_version
            and self.text == ""
            and self._draft_revision == entry.cleared_revision
        )

    def _post_submission_feedback(
        self, *, message_id: str, error_code: Optional[str], restored: bool
    ) -> None:
        """Notify the host of one settled draft outcome through a semantic message.

        Args:
            message_id (str): The settled draft's canonical ID.
            error_code (Optional[str]): The fixed refusal code, if any.
            restored (bool): Whether the editor took the draft's text back.
        """
        self.post_message(
            PromptInputComponent.SubmissionFeedback(
                message_id=message_id, error_code=error_code, restored=restored
            )
        )

    def _record_accepted_message(self, *, text: str, message_id: Optional[str] = None) -> None:
        """Share bounded per-binding identity between receipt and application fallback."""
        if message_id is not None:
            if message_id in self._recorded_message_ids:
                return
            if len(self._recorded_message_order) >= 4096:
                self._recorded_message_ids.remove(self._recorded_message_order.popleft())
            self._recorded_message_order.append(message_id)
            self._recorded_message_ids.add(message_id)
        self._record_accepted_prompt(text=text)

    async def _handle_submission_retry(self, *, command: RetrySubmissionDAO) -> None:
        """Resubmit one retained snapshot with identical bytes and its original ID.

        Args:
            command (RetrySubmissionDAO): Names the retained draft by canonical ID.

        Raises:
            ValueError: The draft is missing, not recoverable, permanent, or foreign.
            DraftCapacityError: The waiting budget is exhausted.
            LookupError: The adapter evicted the retained snapshot.
        """
        if self._submission_sealed or self._submission_adapter is None:
            raise SubmissionUnavailableError()
        entry: Optional[_TrackedDraft] = self._tracked_drafts.get(command.message_id)
        if entry is None or entry.state != "recoverable":
            raise ValueError("This draft cannot be retried; copy its text to send it again.")
        if entry.last_error is not None and entry.last_error.code in (
            "conflict",
            "unauthorized",
            "invalid_message",
        ):
            raise ValueError("This draft cannot be retried; copy its text to send it again.")
        if (
            self._submission_address is None
            or entry.draft_submission.message_submission.target != self._submission_address
        ):
            raise ValueError("Draft belongs to a previous session")
        waiting: int = sum(1 for tracked in self._tracked_drafts.values() if tracked.state == "waiting")
        if waiting >= 4:
            raise DraftCapacityError(reason="in_flight")
        entry.state = "waiting"
        entry.committed = True
        try:
            assert self._submission_adapter is not None
            await self._submission_adapter.handle(event=command)
        except LookupError:
            entry.state = "recoverable"
            raise

    def _discard_recoverable_draft(self, *, command: DiscardDraftDAO) -> None:
        """Drop one recoverable snapshot, releasing its reservation.

        Args:
            command (DiscardDraftDAO): Names the snapshot by canonical ID.

        Raises:
            ValueError: The draft is waiting rather than recoverable.
        """
        entry: Optional[_TrackedDraft] = self._tracked_drafts.get(command.message_id)
        if entry is None:
            return
        if entry.state == "waiting":
            raise ValueError("This draft is still waiting; it cannot be discarded.")
        del self._tracked_drafts[command.message_id]

    def list_recoverable_drafts(self) -> tuple[RecoverableDraftDAO, ...]:
        """List tracked drafts for the host's ``/messages drafts`` view.

        Returns:
            tuple[RecoverableDraftDAO, ...]: Waiting and recoverable snapshots.
        """
        return tuple(
            RecoverableDraftDAO(
                draft_submission=entry.draft_submission,
                state=entry.state,
                last_error_code=entry.last_error.code if entry.last_error is not None else None,
            )
            for entry in self._tracked_drafts.values()
        )

    async def _refresh_slash_suggestions(self) -> None:
        """Request path suggestions when appropriate; otherwise show slash suggestions for the current draft."""
        if self._delivery_closed or self._delivery_closing or not self._is_suggestion_binding_present:
            return
        assert self._suggestion_engine is not None
        prompt_version = self._get_prompt_version()
        if self._path_controller is not None:
            if self._suggestion_engine.owns_arguments(buffer_text=self.text):
                self._path_controller.invalidate()
            elif await self._path_controller.request():
                return
        if self._delivery_closed or not self._is_prompt_version(expected_version=prompt_version):
            return
        self._picker_catalog_revision = ModelSuggestionProjection.current_revision()
        state: SlashSuggestionStateDAO = self._suggestion_engine.evaluate(
            buffer_text=self.text,
            active_model_name=self._active_model_name,
        )
        previous = self._slash_suggestion_state.highlighted_row
        if previous is not None:
            index = next(
                (index for index, row in enumerate(state.rows) if row.insert_text == previous.insert_text), 0
            )
            state = state.model_copy(update={"highlighted_index": index})
        self._slash_suggestion_state = state
        self._render_slash_suggestion_state(state=state)

    def _render_slash_suggestion_state(self, *, state: SlashSuggestionStateDAO) -> None:
        """Update the menu and whether suggestion keys should be handled by this editor."""
        if self._suggestion_menu is not None:
            self._suggestion_menu.update_state(state=state)
        self._suggestion_navigation_enabled = state.visible

    def _build_suggested_prompt_text(
        self,
        *,
        insert_text: str,
        state: SlashSuggestionStateDAO,
    ) -> str:
        """Return the prompt text after accepting one suggestion.

        Args:
            insert_text (str): Accepted suggestion text.
            state (SlashSuggestionStateDAO): Suggestion state describing the replacement span.

        Returns:
            str: Updated prompt text.
        """
        before: str = self.text[: state.replacement_start]
        after: str = self.text[state.replacement_end :]
        return f"{before}{insert_text}{after}"

    def _move_cursor_to_end(self) -> None:
        """Move the prompt cursor to the end of the current buffer."""
        self.move_cursor(self.document.end)

    def _load_prompt_history_text(self, *, text: str) -> None:
        """Load recalled prompt-history text into the editor.

        Args:
            text (str): Prompt text recalled from navigator history.
        """
        self._setting_prompt_from_history = True
        self._prompt_history_navigation_enabled = self._prompt_history.is_navigating
        self.load_text(text)
        self._move_cursor_to_end()

    async def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        """Invalidate path suggestions when the cursor or selection changes in this editor."""
        if event.text_area is not self:
            return
        event.stop()
        if not self._delivery_closed and not self._delivery_closing:
            self.post_message(self.Edited())
            await self._refresh_slash_suggestions()

    async def on_prompt_input_component_path_suggestions_requested(
        self, event: "PromptInputComponent.PathSuggestionsRequested"
    ) -> None:
        """Request path suggestions unless slash-command arguments already control completion."""
        event.stop()
        if (
            not self.is_prompt_intent_current(event=event)
            or self._path_controller is None
            or self._suggestion_engine is None
        ):
            return
        if not self._suggestion_engine.owns_arguments(buffer_text=self.text):
            await self._path_controller.request(explicit=True)

    def _get_prompt_version(self) -> int:
        """Return the editor lifetime captured by queued input and path snapshots."""
        return self._prompt_version

    def _update_prompt_version(self) -> None:
        """Invalidate queued input before reset or suggestion-binding retirement."""
        self._prompt_version += 1

    def _is_prompt_version(self, *, expected_version: int) -> bool:
        """Compare a saved editor lifetime without changing the editor or its binding."""
        return expected_version == self._prompt_version

    @property
    def prompt_version(self) -> int:
        """Return the editor version used to identify outdated path results."""
        return self._prompt_version

    def _is_path_delivery_current(self, *, command: PublishSuggestionsDAO | ReplacePathSpanDAO) -> bool:
        """Accept a path result only from the current controller for unchanged text, cursor, and selection."""
        snapshot = command.snapshot
        return (
            command.controller is self._path_controller
            and self._is_prompt_version(expected_version=snapshot.prompt_version)
            and snapshot.text == self.text
            and snapshot.cursor == self.cursor_location
            and snapshot.selection_empty == self.selection.is_empty
        )

    def _replace_path_span(self, *, command: ReplacePathSpanDAO) -> None:
        """Replace the completed path as one undoable edit."""
        self.history.checkpoint()
        self.replace(
            insert=command.insert_text, start=command.start, end=command.end, maintain_selection_offset=False
        )
        if command.cursor_inside_quote:
            row, column = self.cursor_location
            self.move_cursor(location=(row, column - 1))
        self.history.checkpoint()
