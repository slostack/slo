"""Prompt editor owning local suggestion, recall and model-context state (spec 96.f.2)."""

from __future__ import annotations

from importlib.resources import files
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

__all__ = ["PromptInput"]


class PromptInput(TextArea):
    """``TextArea`` that posts prompt-specific intent messages.

    ``TextArea`` has no ``Submitted`` message of its own (that belongs to
    ``Input``), so we synthesise one. Bare Enter submits; modified Enter
    chords such as Shift+Enter, Cmd+Enter, and Ctrl+Enter insert a literal
    newline instead. When slash suggestions are visible, ``Tab`` / ``Up`` /
    ``Down`` / ``Esc`` are translated into suggestion intent messages so the
    component can keep command composition keyboard-first.

    The component owns the recall navigator, the suggestion state and the
    active model display context. The app mounts the menu, binds it once, and
    owns submission, admission and session selection; editing never invokes an
    agent, persists a message or changes the selected model.
    """

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
        # Constant placeholder: bind takes the real snapshot and refresh returns
        # early while unbound, so the constructor performs no catalog I/O.
        self._picker_catalog_revision: tuple[int, int] = (0, 0)
        self._suggestion_engine: Optional[SlashSuggestionEngine] = None
        self._suggestion_menu: Optional[SlashSuggestionMenu] = None
        self._active_model_name: str = ""
        self._closed: bool = False
        self._path_controller: Optional[PathSuggestionController] = None

    def _set_document(self, text: str, language: Optional[str]) -> None:
        """Build the plain prompt document without normalizing literal path characters.

        TextArea calls this on initialization and load_text; retain its normal
        wrapping/navigation setup and edit history machinery.

        Args:
            text: Literal prompt buffer.
            language: Optional syntax language; non-prompt syntax uses TextArea's setup.
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

    class Edited(Message):
        """Notify the application of buffer or selection changes, without exposing state."""

    class PathSuggestionsRequested(Message):
        """Request explicit path discovery for the current cursor."""

    class Submitted(Message):
        """Posted when the user presses Enter to submit the buffer."""

        def __init__(self, *, text: str) -> None:
            """Carry the submitted text.

            Args:
                text (str): The full multi-line buffer at submit time.
            """
            self.text: str = text
            super().__init__()

    class SuggestionAccepted(Message):
        """Posted when the prompt accepts the highlighted suggestion."""

    class SuggestionMoved(Message):
        """Posted when the prompt moves the highlighted suggestion row."""

        def __init__(self, *, delta: int) -> None:
            """Carry the row movement request.

            Args:
                delta (int): Positive or negative row movement.
            """
            self.delta: int = delta
            super().__init__()

    class SuggestionDismissed(Message):
        """Posted when the prompt dismisses slash suggestions."""

    class PromptHistoryOlderRequested(Message):
        """Posted when the prompt requests the next older prompt."""

    class PromptHistoryNewerRequested(Message):
        """Posted when the prompt requests the next newer prompt."""

    @property
    def _is_bound(self) -> bool:
        """Return whether both the engine and the borrowed menu are present.

        Returns:
            bool: True when suggestion evaluation can reach a mounted menu.
        """
        return self._suggestion_engine is not None and self._suggestion_menu is not None

    def bind_suggestions(
        self,
        *,
        menu: SlashSuggestionMenu,
        engine: SlashSuggestionEngine,
        active_model_name: str,
        path_controller: Optional[PathSuggestionController] = None,
    ) -> None:
        """Bind the borrowed menu and engine once, then evaluate the latest draft.

        Args:
            menu (SlashSuggestionMenu): App-mounted menu this component writes.
            engine (SlashSuggestionEngine): Registry-backed suggestion engine.
            active_model_name (str): Current session model name.

        Raises:
            RuntimeError: When the editor or menu is not mounted, or the
                component is already bound. References stay unmutated.
            Exception: The original evaluation/render failure; borrowed
                references are released first.
        """
        if self._closed or not self.is_mounted or not menu.is_mounted:
            raise RuntimeError("PromptInput is not mounted")
        if self._is_bound:
            raise RuntimeError("PromptInput suggestions are already bound")
        # Snapshot before assigning any collaborator so a revision failure cannot
        # leave a partially bound editor (§4 "No partial binding").
        catalog_revision = ModelSuggestionProjection.current_revision()
        self._adopt_binding(
            menu=menu,
            engine=engine,
            active_model_name=active_model_name,
            catalog_revision=catalog_revision,
        )
        self._path_controller = path_controller
        try:
            self._refresh_slash_suggestions()
        except Exception:
            self._release_failed_binding(menu=menu)
            raise

    def _adopt_binding(
        self,
        *,
        menu: SlashSuggestionMenu,
        engine: SlashSuggestionEngine,
        active_model_name: str,
        catalog_revision: tuple[int, int],
    ) -> None:
        """Adopt the borrowed suggestion collaborators and model context.

        Args:
            menu (SlashSuggestionMenu): App-mounted menu this component writes.
            engine (SlashSuggestionEngine): Registry-backed suggestion engine.
            active_model_name (str): Current session model name.
            catalog_revision (tuple[int, int]): Revision snapshot read before adoption.
        """
        self._suggestion_engine = engine
        self._suggestion_menu = menu
        self._active_model_name = active_model_name
        self._picker_catalog_revision = catalog_revision

    def _release_failed_binding(self, *, menu: SlashSuggestionMenu) -> None:
        """Best-effort hide the borrowed menu, then release every binding reference.

        The cleanup render is best-effort and must not replace the original
        evaluation failure, which bind_suggestions re-raises after this returns.

        Args:
            menu (SlashSuggestionMenu): The still-mounted menu that failed to render.
        """
        try:
            menu.update_state(state=SlashSuggestionStateDAO(visible=False))
        except Exception:
            pass
        self._path_controller = None
        self._suggestion_engine = None
        self._suggestion_menu = None
        self._active_model_name = ""
        self._picker_catalog_revision = (0, 0)
        self._slash_suggestion_state = SlashSuggestionStateDAO(visible=False)
        self._suggestion_navigation_enabled = False

    def hide_suggestions(self) -> None:
        """Hide the bound menu without touching draft, cursor, recall or recency."""
        if self._closed:
            return
        if self._path_controller is not None:
            self._path_controller.dismiss()
            return
        hidden_state: SlashSuggestionStateDAO = SlashSuggestionStateDAO(visible=False)
        self._slash_suggestion_state = hidden_state
        self._render_slash_suggestion_state(state=hidden_state)

    def clear_submission(self) -> None:
        """Hide suggestions and empty the submitted buffer."""
        if self._closed:
            return
        self.hide_suggestions()
        self.load_text("")

    def record_accepted_prompt(self, *, text: str) -> None:
        """Record one accepted ordinary prompt into local recall history.

        Args:
            text (str): Accepted non-slash prompt text.
        """
        if self._closed:
            return
        self._prompt_history.record(text=text)

    def update_model_context(self, *, active_model_name: str) -> None:
        """Adopt a published model name and reevaluate a visible picker.

        Args:
            active_model_name (str): Current session model name.
        """
        if self._closed or not self._is_bound:
            # §5.5: model notifications before bind are no-ops; bind supplies context.
            return
        self._active_model_name = active_model_name
        if self._slash_suggestion_state.visible:
            self._refresh_slash_suggestions()

    def record_model_selection(self, *, model_name: str) -> None:
        """Remember one changed slash model selection in local recency.

        Args:
            model_name (str): Newly selected model name.
        """
        if self._closed or not self._is_bound:
            return
        assert self._suggestion_engine is not None
        self._suggestion_engine.record_selection(model_name=model_name)

    def refresh_published_suggestions(self) -> None:
        """Refresh a visible picker when the published catalog revision changed."""
        if self._closed or not self._is_bound:
            return
        if not self._slash_suggestion_state.visible or self._slash_suggestion_state.kind != "slash":
            return
        if ModelSuggestionProjection.current_revision() == self._picker_catalog_revision:
            return
        self._refresh_slash_suggestions()

    def reset_session(self) -> None:
        """Drop recall, hide suggestions and empty the draft for an adopted session."""
        if self._closed:
            return
        self._prompt_history = PromptHistoryNavigator()
        self._setting_prompt_from_history = False
        self._prompt_history_navigation_enabled = False
        self.hide_suggestions()
        self.load_text("")

    async def _on_key(self, event: events.Key) -> None:
        """Intercept Enter chords for submit/newline semantics.

        Args:
            event (events.Key): The key event from Textual.
        """
        if self._should_accept_suggestion(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionAccepted())
            return
        if event.key == "tab":
            event.prevent_default()
            event.stop()
            self.post_message(self.PathSuggestionsRequested())
            return
        if self._should_move_suggestion(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.SuggestionMoved(delta=self._suggestion_delta(event=event)))
            return
        if self._should_request_older_prompt(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.PromptHistoryOlderRequested())
            return
        if self._should_request_newer_prompt(event=event):
            event.prevent_default()
            event.stop()
            self.post_message(self.PromptHistoryNewerRequested())
            return
        if self._should_dismiss_suggestions(event=event):
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

    def _should_accept_suggestion(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should accept a suggestion.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the suggestion menu should accept the current row.
        """
        return self._suggestion_navigation_enabled and event.key == "tab"

    def _should_move_suggestion(self, *, event: events.Key) -> bool:
        """Return True when ``event`` should move the highlight.

        Args:
            event (events.Key): Key event under inspection.

        Returns:
            bool: True when the highlighted suggestion should move.
        """
        return self._suggestion_navigation_enabled and event.key in {"up", "down"}

    def _should_request_older_prompt(self, *, event: events.Key) -> bool:
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

    def _should_request_newer_prompt(self, *, event: events.Key) -> bool:
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

    def _should_dismiss_suggestions(self, *, event: events.Key) -> bool:
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

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Process the owned buffer change, then refresh suggestions.

        Args:
            event (TextArea.Changed): Buffer change event from any editor.
        """
        if event.text_area is not self:
            return
        event.stop()
        if self._closed:
            return
        self.post_message(self.Edited())
        if self._setting_prompt_from_history:
            self._setting_prompt_from_history = False
        elif self._prompt_history.is_navigating:
            self._prompt_history.clear_navigation()
            self._prompt_history_navigation_enabled = False
        self._refresh_slash_suggestions()

    def on_prompt_input_suggestion_moved(self, event: "PromptInput.SuggestionMoved") -> None:
        """Move the highlighted slash suggestion row.

        Args:
            event (PromptInput.SuggestionMoved): Requested row movement.
        """
        event.stop()
        if self._closed or not self._is_bound:
            return
        if not self._slash_suggestion_state.visible:
            return
        self._slash_suggestion_state = self._slash_suggestion_state.with_highlight_delta(delta=event.delta)
        self._render_slash_suggestion_state(state=self._slash_suggestion_state)

    def on_prompt_input_suggestion_dismissed(self, event: "PromptInput.SuggestionDismissed") -> None:
        """Dismiss visible slash suggestions.

        Args:
            event (PromptInput.SuggestionDismissed): Dismissal request.
        """
        event.stop()
        if self._closed or not self._is_bound:
            return
        self.hide_suggestions()

    def on_prompt_input_suggestion_accepted(self, event: "PromptInput.SuggestionAccepted") -> None:
        """Accept the highlighted slash suggestion when visible.

        Args:
            event (PromptInput.SuggestionAccepted): Acceptance request.
        """
        event.stop()
        if self._closed or not self._is_bound:
            return
        row = self._slash_suggestion_state.highlighted_row
        if row is None:
            return
        if self._slash_suggestion_state.kind == "path" and self._path_controller is not None:
            self._path_controller.accept(insert_text=row.insert_text)
            return
        updated_text: str = self._replace_prompt_text(
            insert_text=row.insert_text,
            state=self._slash_suggestion_state,
        )
        self.load_text(updated_text)
        self._move_cursor_to_end()
        self._refresh_slash_suggestions()

    def on_prompt_input_prompt_history_older_requested(
        self,
        event: "PromptInput.PromptHistoryOlderRequested",
    ) -> None:
        """Load the next older prompt into the editor when available.

        Args:
            event (PromptInput.PromptHistoryOlderRequested): History request.
        """
        event.stop()
        if self._closed:
            return
        recalled_text: Optional[str] = self._prompt_history.older(current_buffer=self.text)
        if recalled_text is None:
            return
        self._load_prompt_history_text(text=recalled_text)

    def on_prompt_input_prompt_history_newer_requested(
        self,
        event: "PromptInput.PromptHistoryNewerRequested",
    ) -> None:
        """Load the next newer prompt into the editor when available.

        Args:
            event (PromptInput.PromptHistoryNewerRequested): History request.
        """
        event.stop()
        if self._closed:
            return
        recalled_text: Optional[str] = self._prompt_history.newer()
        if recalled_text is None:
            return
        self._load_prompt_history_text(text=recalled_text)

    def on_unmount(self) -> None:
        """Mark the editor closed and release every borrowed suggestion reference."""
        self._closed = True
        self._suggestion_navigation_enabled = False
        self._prompt_history_navigation_enabled = False
        self._setting_prompt_from_history = False
        self._slash_suggestion_state = SlashSuggestionStateDAO(visible=False)
        self._path_controller = None
        self._suggestion_engine = None
        self._suggestion_menu = None

    def _refresh_slash_suggestions(self) -> None:
        """Recompute slash suggestions from the current buffer and model context."""
        if self._closed or not self._is_bound:
            return
        assert self._suggestion_engine is not None
        if self._path_controller is not None:
            if self._suggestion_engine.owns_arguments(buffer_text=self.text):
                self._path_controller.invalidate()
            elif self._path_controller.request():
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
        """Render one suggestion state into the bound menu and interception flag.

        Args:
            state (SlashSuggestionStateDAO): Suggestion state to render.
        """
        if self._suggestion_menu is not None:
            self._suggestion_menu.update_state(state=state)
        self._suggestion_navigation_enabled = state.visible

    def _replace_prompt_text(
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

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        """Invalidate cursor-local completion when the owned selection moves."""
        if event.text_area is not self:
            return
        event.stop()
        if not self._closed:
            self.post_message(self.Edited())
            self._refresh_slash_suggestions()

    def on_prompt_input_path_suggestions_requested(
        self, event: "PromptInput.PathSuggestionsRequested"
    ) -> None:
        """Request explicit discovery unless enumerated slash arguments own input."""
        event.stop()
        if self._closed or self._path_controller is None or self._suggestion_engine is None:
            return
        if not self._suggestion_engine.owns_arguments(buffer_text=self.text):
            self._path_controller.request(explicit=True)

    def publish_path_suggestions(self, *, state: SlashSuggestionStateDAO) -> None:
        """Paint a current controller result through the single owned menu state."""
        if self._closed:
            return
        self._slash_suggestion_state = state
        self._render_slash_suggestion_state(state=state)
