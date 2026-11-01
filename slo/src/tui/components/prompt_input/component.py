"""Prompt editor owning local suggestion, recall and model-context state (spec 96.f.2)."""

from __future__ import annotations

import asyncio
from importlib.resources import files

from src.tui.components.prompt_input.commands import (
    ClearSubmissionDAO,
    PromptCommand,
    ReplacePromptDAO,
    HideSuggestionsDAO,
    RecordAcceptedPromptDAO,
    SetModelContextDAO,
    RecordModelSelectionDAO,
    RefreshPublishedSuggestionsDAO,
    PublishSuggestionsDAO,
    ReplacePathSpanDAO,
)
from typing import ClassVar, Optional

from textual import events
from textual.message import Message
from textual.document._wrapped_document import WrappedDocument
from textual.document._document_navigator import DocumentNavigator
from src.tui.widgets.prompt_document import PromptDocument
from src.tui.path_suggestion_controller import PathSuggestionController
from textual.widgets import TextArea

from src.tui.model_catalog import ModelSuggestionProjection
from src.tui.prompt_history import PromptHistoryNavigator
from src.tui.slash_suggestion_engine import SlashSuggestionEngine, SlashSuggestionStateDAO
from src.tui.widgets.slash_suggestion_menu import SlashSuggestionMenu

__all__ = ["PromptInputComponent"]


class _PromptIntent(Message):
    """Carry the emitting editor prompt_version across Textual's native message queue."""

    def __init__(self) -> None:
        """Leave direct handler calls unbound; posting stamps the actual emitter."""
        super().__init__()
        self.prompt: Optional[PromptInputComponent] = None
        self.prompt_version: Optional[int] = None


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
        self._prompt_version: int = 0
        self._path_controller: Optional[PathSuggestionController] = None

    def _set_document(self, text: str, language: Optional[str]) -> None:
        """Create a prompt document that preserves path characters exactly.

        Keep Textual’s normal wrapping, cursor movement, and edit history. Use its
        normal document setup when a syntax language is requested.
        """
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

    def post_message(self, message: Message) -> bool:
        """Mark outgoing prompt messages with the current editor state before Textual queues them."""
        if isinstance(message, _PromptIntent) and message.prompt_version is None:
            message.prompt = self
            message.prompt_version = self._get_prompt_version()
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
        return self.is_mounted and not self._delivery_closed

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
        if self._delivery_closed:
            raise RuntimeError("PromptInputComponent is closed")

    def _ensure_prompt_mounted(self) -> None:
        """Require native mounting before accessing the editor's application."""
        if not self.is_mounted:
            raise RuntimeError("PromptInputComponent requires its mounted UI loop")

    def _ensure_prompt_ui_loop(self) -> None:
        """Raise RuntimeError for mutation attempted outside the mounted UI loop."""
        if asyncio.get_running_loop() is not self.app._loop:
            raise RuntimeError("PromptInputComponent requires its mounted UI loop")

    async def handle(self, *, command: PromptCommand) -> None:
        """Apply a supported editor command on the UI loop without waiting for the screen to repaint.

        Finish text edits and menu updates directly. Await controller callbacks
        without starting another task or acquiring a lock twice. The app still owns
        filesystem reads. Reject unknown commands and calls after close.
        """
        self._ensure_prompt_open()
        self._ensure_prompt_mounted()
        self._ensure_prompt_ui_loop()
        if isinstance(command, ClearSubmissionDAO):
            self.load_text("")
            await self._hide_suggestions()
        elif isinstance(command, ReplacePromptDAO):
            self.load_text(command.text)
            self._move_cursor_to_end()
        elif isinstance(command, HideSuggestionsDAO):
            await self._hide_suggestions()
        elif isinstance(command, RecordAcceptedPromptDAO):
            self._record_accepted_prompt(text=command.text)
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
        self._update_prompt_version()
        await self._reset_session()

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
        if self._delivery_closed:
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
        if self._delivery_closed:
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
        """Stop accepting input and release references to the supplied suggestion tools.

        Release references even if cleanup fails, and report that failure once.
        Later close calls do nothing. The app, not this editor, stops and waits
        for the path controller’s filesystem work.
        """
        if self.is_mounted and asyncio.get_running_loop() is not self.app._loop:
            raise RuntimeError("PromptInputComponent requires its mounted UI loop")
        if self._delivery_closed:
            return
        self._delivery_closed = True
        self._retire_suggestion_binding()

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

    async def _refresh_slash_suggestions(self) -> None:
        """Request path suggestions when appropriate; otherwise show slash suggestions for the current draft."""
        if self._delivery_closed or not self._is_suggestion_binding_present:
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
        if not self._delivery_closed:
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
