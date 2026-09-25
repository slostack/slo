"""Streaming assistant-answer widget for transcript-visible answer text."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.content import Content, Span
from textual.containers import Vertical
from textual.message import Message
from textual.selection import Selection
from textual.timer import Timer
from textual.widgets import Static

from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.markdown_content_compiler import (
    MarkdownContentCompiler,
    MarkdownContentDAO,
    _resolve_semantic_spans,
)

__all__ = ["AssistantStreamBlock"]

_STREAM_FLUSH_INTERVAL_SECONDS: float = 1.0 / 30.0
"""Coalescing cadence for streamed answer renders (~30 fps)."""


class AssistantAnswerBody(Static):
    """Answer-only body whose compiled visible Markdown remains selectable.

    WHAT: Compiles owner-held raw Markdown to Textual ``Content`` and serves
    that visible buffer to native selection. ``Content`` supplies truthful
    per-cell offsets and native selection paint without an offset mapper.
    WHO: ``AssistantStreamBlock`` owns one instance as ``_answer_body``;
    ``Screen.get_selected_text`` queries it after a mouse selection.
    WHEN: Updated at every answer render boundary; queried whenever the
    screen extracts selected text.
    """

    def __init__(self, *, classes: Optional[str] = None) -> None:
        """Initialise an empty answer surface.

        Args:
            classes (Optional[str]): Space-separated CSS classes.
        """
        super().__init__(content="", classes=classes)
        self._raw_markdown: str = ""
        self._visible_text: str = ""

    def show_answer(self, *, text: str) -> None:
        """Compile and render owner-held raw Markdown through Textual Content.

        WHAT: Stores raw Markdown, compiles its visible buffer, then updates
        one `Content` visual or hides the surface when visible text is empty.
        WHO: ``AssistantStreamBlock._render_answer`` calls it after accepted
        streamed or final text.
        WHEN: Runs at an answer render boundary.

        Args:
            text (str): Raw assistant answer text.
        """
        self._raw_markdown = text
        compilation = MarkdownContentCompiler.compile(raw_markdown=text)
        self._visible_text = compilation.visible_text
        if not self._visible_text:
            self.update("")
            self.display = False
            return
        self.display = True
        self.update(
            Content(text=self._visible_text, spans=list(self._resolved_spans(compilation=compilation)))
        )

    def _resolved_spans(self, *, compilation: MarkdownContentDAO) -> tuple[Span, ...]:
        """Resolve semantic spans only after this body is mounted in an app."""
        if not self.is_mounted:
            return compilation.spans
        return _resolve_semantic_spans(
            spans=compilation.spans, theme_variables=self.app.current_theme.variables
        )

    def get_selection(self, selection: Selection) -> Optional[tuple[str, str]]:
        """Return the selected slice of the visible answer buffer.

        WHAT: Serves the raw (unescaped) answer text through Textual's
        documented custom-widget selection seam so a mouse drag over the
        flattened answer surface yields the answer itself.
        WHO: ``Screen.get_selected_text`` calls it for every widget captured
        by a mouse selection.
        WHEN: After a drag selection starts, moves, or completes.

        Args:
            selection (Selection): The selected range in content coordinates.

        Returns:
            Optional[tuple[str, str]]: Extracted visible answer text and its line
                ending, or ``None`` when no answer text exists.
        """
        if not self._visible_text:
            return None
        return selection.extract(self._visible_text), "\n"


class AssistantStreamBlock(Vertical):
    """Render one in-flight assistant answer.

    WHAT: Owns answer text, answer rendering/coalescing, terminal state, and
    the optional title prefix. Copy behaviour lives entirely on the shared
    TUI clipboard paths (focus-chord and mouse selection); no card-local copy
    control exists after ``72.a.3``.
    WHO: ``TranscriptProjector`` updates it for ``text_*`` and terminal events.
    WHEN: One block is mounted per outer-loop answer iteration. Thinking renders
    in a separate ``AssistantStreamThinkingBlock`` segment.
    """

    class Rendered(Message):
        """Posted after either assistant-side widget flushes a changed buffer.

        Both ``AssistantStreamBlock`` (answer updates) and
        ``AssistantStreamThinkingBlock`` (reasoning updates) post this shared
        message after their coalescing timer applies a ``Static.update``. The
        app handles it to re-check scroll-follow: because the timer fires
        *after* the per-mount ``_restore_follow_after_mutation`` has already
        run, the ``Static.update`` expands ``max_scroll_y`` without a
        scroll-end call. This message lets the app schedule a scroll
        restoration on the next refresh.

        ``was_following`` carries the pre-flush follow state so the app can
        restore scroll-end when the viewport was at the bottom before the
        ``Static.update`` expanded ``max_scroll_y``.
        """

        def __init__(self, *, was_following: bool) -> None:
            """Initialise the rendered notification.

            Args:
                was_following (bool): True when the viewport was at the bottom
                    immediately before the flush, so the app knows to restore
                    scroll-end.
            """
            super().__init__()
            self.was_following: bool = was_following

    can_focus: bool = True

    DEFAULT_CSS = """
    AssistantStreamBlock .sub-agent-label {
        color: $text-muted;
        text-style: dim;
        margin: 0 0 0 0;
        padding: 0 1;
    }

    AssistantStreamBlock {
        width: 100%;
        height: auto;
        margin: 1 0 1 0;
        padding: 0 1;
        background: transparent;
    }

    AssistantStreamBlock .assistant-answer-body {
        color: $text;
        background: transparent;
        text-style: none;
    }

    AssistantStreamBlock .assistant-terminal-warning {
        color: $warning;
        text-style: italic;
    }
    """

    def __init__(
        self,
        *,
        title_prefix: Optional[str] = None,
    ) -> None:
        """Seed an empty assistant answer block.

        Args:
            title_prefix (Optional[str]): When set, renders a dim single-line
                label above the block's content using the ``sub-agent-label``
                CSS class. ``None`` (default) produces no label and the block
                renders identically to the pre-feature behaviour.
        """
        super().__init__()
        self._title_prefix: Optional[str] = title_prefix
        self._label: Optional[LiteralTextStatic] = (
            LiteralTextStatic(title_prefix, classes="sub-agent-label") if title_prefix else None
        )
        self._answer_body: AssistantAnswerBody = AssistantAnswerBody(classes="assistant-answer-body")
        self._answer_body.display = False
        self._terminal_note: LiteralTextStatic = LiteralTextStatic("", classes="assistant-terminal-warning")
        self._terminal_note.display = False
        self._answer_text: str = ""
        self._terminal_note_text: str = ""
        self._finalized: bool = False
        self._answer_dirty: bool = False
        self._last_rendered_answer: str = ""
        self._flush_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        """Compose the visible child widgets.

        Yields the optional label first, then the two logical transcript
        regions (answer, terminal note). Omits the label when ``title_prefix``
        was not supplied.

        Yields:
            ComposeResult: Optional label then the answer-side regions.
        """
        if self._label is not None:
            yield self._label
        yield self._answer_body
        yield self._terminal_note

    def on_unmount(self) -> None:
        """Flush and cancel the timer when the block leaves the DOM."""
        self._stop_flush_timer()

    def _ensure_flush_timer(self) -> None:
        """Start the coalescing timer on the first streamed delta, if mounted.

        Called by the answer scheduler. No-op when unmounted (the scheduler
        renders synchronously instead), when already running, or once finalized.
        """
        if self._flush_timer is None and self.is_mounted and not self._finalized:
            self._flush_timer = self.set_interval(
                interval=_STREAM_FLUSH_INTERVAL_SECONDS,
                callback=self._flush_dirty_regions,
                name="assistant-stream-flush",
            )

    def _stop_flush_timer(self) -> None:
        """Flush any pending render, then stop and drop the coalescing timer.

        Flushing first guarantees the last streamed frame is on screen before
        the timer dies, so finalize/seal/abort/failure never drop the final
        (<=1 frame) of accumulated text. Called on unmount and every
        finalization path.
        """
        self._flush_dirty_regions()
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None

    def _flush_dirty_regions(self) -> None:
        """Flush a changed answer and emit the shared scroll-follow message.

        WHAT: Retains the existing answer timer callback name while making one
        answer-only render decision.
        WHO: The answer timer and terminal paths call it.
        WHEN: After answer deltas or at an answer terminal boundary.
        """
        if not self._answer_dirty:
            return
        was_following: bool = self._check_app_at_bottom()
        self._flush_answer()
        if self.is_mounted:
            self.post_message(AssistantStreamBlock.Rendered(was_following=was_following))

    def _check_app_at_bottom(self) -> bool:
        """Return True when the transcript viewport is effectively at the bottom.

        Reads the scroll state from the app via duck-typing without importing
        ``SloTUI`` (which would create a circular dependency). When unmounted
        or when the app does not expose ``_transcript_is_at_bottom``, returns
        ``False`` (safe default — no spurious scroll-end).

        Returns:
            bool: True when the transcript viewport is within one line of the
                scroll bottom.
        """
        if not self.is_mounted:
            return False
        check = getattr(self.app, "_transcript_is_at_bottom", None)
        if check is None:
            return False
        return bool(check())

    def _flush_answer(self) -> None:
        """Render the accumulated answer, skipping work when text is unchanged.

        Clears the answer dirty flag and re-renders only when the accumulated
        text differs from the last rendered snapshot, so an idle tick or a
        finalize matching the streamed text costs nothing.
        """
        self._answer_dirty = False
        if self._answer_text == self._last_rendered_answer:
            return
        self._last_rendered_answer = self._answer_text
        self._render_answer()

    def _schedule_answer_render(self) -> None:
        """Mark the answer dirty; render now when unmounted, else coalesce.

        Called by ``append_text``. When mounted, the coalescing timer performs
        the ``Static.update`` on the next tick so a burst of deltas produces
        one render per frame. Before mount (direct unit-test construction,
        ``is_mounted`` is ``False``) there is no timer, so we render
        synchronously to preserve the direct-assertion widget contract.
        """
        self._answer_dirty = True
        if not self.is_mounted:
            self._flush_answer()
            return
        self._ensure_flush_timer()

    @property
    def answer_text(self) -> str:
        """Return accumulated answer text.

        Returns:
            str: Raw answer text used by terminal treatment and focused copy.
        """
        return self._answer_text

    @property
    def terminal_note_text(self) -> str:
        """Return the terminal note text.

        Returns:
            str: Terminal note text.
        """
        return self._terminal_note_text

    @property
    def finalized(self) -> bool:
        """Return whether the block has been finalized.

        Returns:
            bool: True when the block should stop accepting deltas.
        """
        return self._finalized

    def get_copyable_text(self) -> str:
        """Return the visible answer, compiling a direct raw test/update assignment if needed.

        Returns:
            str: This block's visible answer, never a reasoning segment.
        """
        if self._answer_text != self._answer_body._raw_markdown:
            self._answer_body.show_answer(text=self._answer_text)
        return self.visible_answer_text

    @property
    def visible_answer_text(self) -> str:
        """Return the answer body's compiler-emitted visible text."""
        return self._answer_body._visible_text

    def get_raw_markdown_for_copy(self) -> str:
        """Return the complete raw Markdown for the explicit raw-copy action."""
        return self._answer_text

    def append_text(self, *, delta: str) -> None:
        """Append visible assistant answer text.

        Args:
            delta (str): Incremental assistant answer text.
        """
        if self._finalized or not delta:
            return
        self._answer_text += delta
        self._schedule_answer_render()

    def set_answer(self, *, content: str) -> None:
        """Replace the visible answer text with completed truth.

        Args:
            content (str): Completed visible answer text.
        """
        if self._finalized or not content:
            return
        self._answer_text = content
        self._answer_dirty = True
        self._flush_answer()

    def finalize(self, *, final_text: str) -> None:
        """Finalize the block using completed assistant text.

        The completed assistant text from the runtime is the source of truth and
        overwrites any in-flight streamed answer. Marks the final text dirty,
        then stops the timer — which flushes it synchronously first, so the final
        answer is on screen immediately and no later tick fires.

        Args:
            final_text (str): Completed assistant answer text.
        """
        if self._finalized:
            return
        self._answer_text = final_text
        self._answer_dirty = True
        self._finalized = True
        self._stop_flush_timer()

    def mark_aborted(self) -> None:
        """Mark the block as aborted while preserving partial content."""
        if self._finalized:
            return
        self._terminal_note_text = "(aborted)"
        self._terminal_note.display = True
        self._terminal_note.update(self._terminal_note_text)
        self._finalized = True
        self._stop_flush_timer()

    def mark_failed(self, *, error_message: str) -> None:
        """Mark the block as failed while preserving partial content.

        Args:
            error_message (str): One-line user-visible error summary.
        """
        if self._finalized:
            return
        self._terminal_note_text = f"(error: {error_message})"
        self._terminal_note.display = True
        self._terminal_note.update(self._terminal_note_text)
        self._finalized = True
        self._stop_flush_timer()

    def seal(self) -> None:
        """Mark the block finalized without overwriting any streamed content.

        Called by ``TranscriptProjector._finalize_completed_run`` when
        ``run_completed`` fires with no confirmed final text. Stops the block
        from accepting further ``append_text`` deltas while preserving
        whatever was already streamed into the answer region. Flushes pending
        dirty regions before stopping the timer so the last streamed delta is
        always on screen.
        """
        if self._finalized:
            return
        self._finalized = True
        self._stop_flush_timer()

    def _render_answer(self) -> None:
        """Render the current answer on the answer surface.

        WHAT: Hands the accumulated raw answer text to the answer surface,
        which renders compiler-visible ``Content`` or hides itself when no
        answer text exists.
        WHO: ``_flush_answer`` calls it after accepted streamed or final text.
        WHEN: Runs at an answer render boundary.
        """
        self._answer_body.show_answer(text=self._answer_text)
