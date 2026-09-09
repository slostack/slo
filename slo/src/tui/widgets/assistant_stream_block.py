"""Streaming assistant-answer widget for transcript-visible answer text."""

from __future__ import annotations

from typing import Optional

from rich.markdown import Markdown
from rich.padding import Padding
from textual.app import ComposeResult, RenderResult
from textual.containers import Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker

from src.tui.mermaid_fence_segmenter import AnswerSegmentDAO, MermaidFenceSegmenter
from src.tui.widgets.literal_text_static import LiteralTextStatic
from src.tui.widgets.mermaid_chart_block import MermaidChartBlock
from src.tui.widgets.selectable_rich_visual import SelectableRawTextLeaf

__all__ = ["AnswerMarkdownPart", "AssistantStreamBlock"]

_STREAM_FLUSH_INTERVAL_SECONDS: float = 1.0 / 30.0
"""Coalescing cadence for streamed answer renders (~30 fps)."""


def _escape_markdown_breakers(*, text: str) -> str:
    """Escape angle-bracket fragments that break transcript readability.

    WHAT: Rewrites literal ``<`` and ``>`` so Rich's markdown parser cannot
    read them as markup. It is the single implementation of an escape that
    previously existed as two identical private copies.
    WHO: ``AnswerMarkdownPart.show_segment`` and
    ``AssistantStreamThinkingBlock._stabilize_reasoning_markdown``.
    WHEN: On prose text only — never on mermaid source, which this escape
    would corrupt (``-->`` becomes ``--\\>``).

    Args:
        text (str): Raw assistant answer or reasoning text.

    Returns:
        str: Stabilized markdown text.
    """
    return text.replace("<", "\\<").replace(">", "\\>")


def _transcript_is_at_bottom(*, widget: Widget) -> bool:
    """Return True when the transcript viewport is effectively at the bottom.

    WHAT: Reads the scroll state from the app by duck-typing, without
    importing ``SloTUI`` (which would create a circular dependency). Returns
    ``False`` when unmounted or when the app does not expose the hook — the
    safe default, since it only suppresses a scroll-end.
    WHO: ``AssistantStreamBlock._flush_dirty_regions``,
    ``AssistantAnswerBody._drain_reconciliations``, and
    ``AssistantStreamThinkingBlock._flush`` — the single implementation of a
    reading that previously existed as two identical ``_check_app_at_bottom``
    copies.
    WHEN: Immediately before a render or DOM transaction that can grow
    ``max_scroll_y``.

    Args:
        widget (Widget): Any mounted widget on the transcript.

    Returns:
        bool: True when the transcript viewport is within one line of the
            scroll bottom.
    """
    if not widget.is_mounted:
        return False
    check = getattr(widget.app, "_transcript_is_at_bottom", None)
    if check is None:
        return False
    return bool(check())


class AnswerMarkdownPart(SelectableRawTextLeaf):
    """One markdown segment of a segmented answer, selectable in its own right.

    WHAT: Renders one text segment as the same padded ``Markdown`` the
    unsegmented body used; the raw segment text and the drag highlight come
    from the inherited ``SelectableRawTextLeaf`` seams (``get_selection``
    plus the ``SelectableRichVisual`` render wrap).
    WHO: ``AssistantAnswerBody._build_segment_child`` builds one per text
    segment and updates it in place through ``show_segment``.
    WHEN: Built at an answer render boundary; updated on every subsequent
    flush whose tail text grew.

    It extends the shared leaf rather than re-implementing the seam —
    ``AssistantAnswerBody`` becomes a container the moment it mounts
    children, and Textual's ``SelectState._walk_selected_widgets`` skips
    containers, so a selection seam on the body would never be called.
    """

    def __init__(self, *, raw_text: str) -> None:
        """Seed the part with one raw answer segment.

        Args:
            raw_text (str): Raw, unescaped text of this segment.
        """
        super().__init__(classes="assistant-answer-markdown-part")
        self.show_segment(raw_text=raw_text)

    @property
    def raw_text(self) -> str:
        """Return this part's raw segment text.

        Returns:
            str: The unescaped segment content currently rendered.
        """
        return self._raw_text

    def show_segment(self, *, raw_text: str) -> None:
        """Update this part in place from one raw answer segment.

        WHAT: Re-renders the padded markdown without remounting the widget,
        which is what keeps the streaming tail from being torn down ~30 times
        a second.
        WHO: ``AssistantAnswerBody.reconcile_segments`` calls it for a reused
        text child.
        WHEN: Whenever the segment at this index grew or changed.

        Args:
            raw_text (str): Raw, unescaped text of this segment.
        """
        self.set_source_text(text=raw_text)
        self.update(
            Padding(
                renderable=Markdown(_escape_markdown_breakers(text=raw_text)),
                pad=(1, 0, 1, 0),
            )
        )


class AssistantAnswerBody(Static):
    """Answer-only segmented surface composed of selectable leaves.

    WHAT: Splits the raw answer into text/mermaid segments and reconciles one
    child per segment — an ``AnswerMarkdownPart`` for text, a
    ``MermaidChartBlock`` for each closed mermaid fence. It is a container,
    so it owns no selection seam of its own; each child owns its own.
    WHO: ``AssistantStreamBlock`` owns one instance as ``_answer_body``.
    WHEN: Re-composed at every answer render boundary.
    """

    def __init__(self, *, classes: Optional[str] = None) -> None:
        """Initialise an empty answer surface.

        Args:
            classes (Optional[str]): Space-separated CSS classes.
        """
        super().__init__(content="", classes=classes)
        self._mounted_segments: list[AnswerSegmentDAO] = []
        self._pending_children: list[Widget] = []
        self._pending_segments: list[AnswerSegmentDAO] = []
        self._reconcile_worker: Optional[Worker[None]] = None

    def show_answer(self, *, text: str) -> None:
        """Re-compose the answer surface from segmented parts.

        WHAT: Segments the RAW answer (escaping corrupts mermaid edge
        syntax), then schedules the serialized reconciliation. Hides the
        surface when no answer text exists. Never mutates ``self.children``
        itself. The raw answer itself is not stored here — each part owns its
        own segment text, and ``AssistantStreamBlock`` owns the whole answer.
        WHO: ``AssistantStreamBlock._render_answer`` calls it after accepted
        streamed or final text.
        WHEN: Runs at an answer render boundary (at most 30 times a second by
        the flush timer).

        Args:
            text (str): Raw assistant answer text.
        """
        if not text:
            self._mounted_segments = []
            self._pending_children = []
            self.display = False
            return
        self.display = True
        segments: list[AnswerSegmentDAO] = MermaidFenceSegmenter.segment(text=text)
        if not self.is_mounted:
            # Before mount there is no DOM to reconcile and no worker to run:
            # stage the children for ``compose``. This covers direct
            # unit-test construction and the replay path, where ``finalize``
            # can land before the mount completes.
            self._mounted_segments = segments
            self._pending_children = [self._build_segment_child(segment=segment) for segment in segments]
            return
        self._schedule_reconciliation(segments=segments)

    def compose(self) -> ComposeResult:
        """Yield the children ``show_answer`` staged before mount.

        WHO: Textual calls it during mount; the answer-body unit tests read
        the same staged list to inspect the direct-construction path.
        WHEN: Once per mount, after any pre-mount ``show_answer``.

        Yields:
            ComposeResult: The children staged by ``show_answer``.
        """
        yield from self._pending_children

    def render(self) -> RenderResult:
        """Return the (always empty) own content of a container surface.

        The body never calls ``update`` after the reshape — its visible
        content is entirely its children — so this returns the empty string
        it was constructed with. The selection-aware wrap moved to
        ``AnswerMarkdownPart``.

        WHO: Textual's ``Widget._render`` calls it on every repaint.
        WHEN: At every render pass while the body is mounted.

        Returns:
            RenderResult: The stored string content.
        """
        return self.content

    def on_unmount(self) -> None:
        """Cancel any in-flight reconciliation when the body leaves the DOM.

        The body owns its worker, so it also owns the cancel — honouring the
        TUI rule that background tasks are tracked and cancelled explicitly.
        ``AssistantStreamBlock.on_unmount`` is unchanged.
        """
        if self._reconcile_worker is None:
            return
        self._reconcile_worker.cancel()
        self._reconcile_worker = None

    def _schedule_reconciliation(self, *, segments: list[AnswerSegmentDAO]) -> None:
        """Coalesce the latest segment list into one serialized reconciliation.

        WHAT: Stores the newest requested segments (latest wins) and starts
        the tracked worker only when none is running, so a burst of flush
        ticks collapses into one in-flight DOM transaction plus at most one
        follow-up — later requests can never interleave with an awaiting
        removal/mount sequence.
        WHO: ``show_answer`` calls it with fresh segments.
        WHEN: At every answer render boundary while the body is mounted.

        Args:
            segments (list[AnswerSegmentDAO]): Latest requested ordered parts.
        """
        self._pending_segments = segments
        if self._reconcile_worker is not None and self._reconcile_worker.is_running:
            return
        self._reconcile_worker = self.run_worker(
            self._drain_reconciliations(),
            group="answer-surface-reconciliation",
            exit_on_error=False,
        )

    async def _drain_reconciliations(self) -> None:
        """Apply the latest coalesced segments, then report the settled DOM.

        WHAT: Drains the latest-wins pending list until no newer request
        arrived while the body awaited its removals and mounts. It reads the
        scroll-follow state BEFORE each transaction and posts
        ``AssistantStreamBlock.Rendered`` AFTER it, because the DOM now grows
        asynchronously — ``_flush_dirty_regions``'s synchronous post happens
        before the height change and would otherwise re-scroll against a
        stale height, unpinning the transcript mid-stream.
        WHO: The tracked worker started by ``_schedule_reconciliation``.
        WHEN: After a changed answer flush; cancelled during teardown.
        """
        while True:
            segments: list[AnswerSegmentDAO] = self._pending_segments
            was_following: bool = _transcript_is_at_bottom(widget=self)
            await self.reconcile_segments(segments=segments)
            self.post_message(AssistantStreamBlock.Rendered(was_following=was_following))
            if self._pending_segments is segments:
                return

    async def reconcile_segments(self, *, segments: list[AnswerSegmentDAO]) -> None:
        """Reconcile mounted answer-part widgets to one requested segment list.

        WHAT: Removes the divergent mounted suffix, mounts its replacement,
        then updates every reused text child in place. Every stale removal is
        awaited before the replacement mount is awaited, and
        ``_mounted_segments`` is committed only after the awaited DOM state
        corresponds to it — so a later reconciliation never slices
        ``self.children`` against a stale snapshot.
        WHO: ``_drain_reconciliations`` awaits it (exactly one in flight).
        WHEN: After the 30-fps answer flush accepts changed raw text.

        Args:
            segments (list[AnswerSegmentDAO]): Ordered raw-answer parts to render.
        """
        reusable: int = self._reusable_prefix_length(segments=segments)
        for child in list(self.children)[reusable:]:
            await child.remove()
        replacements: list[Widget] = [
            self._build_segment_child(segment=segment) for segment in segments[reusable:]
        ]
        if replacements:
            await self.mount(*replacements)
        for index, segment in enumerate(segments[:reusable]):
            child = self.children[index]
            if isinstance(child, AnswerMarkdownPart) and child.raw_text != segment.content:
                child.show_segment(raw_text=segment.content)
        self._mounted_segments = list(segments)

    def _reusable_prefix_length(self, *, segments: list[AnswerSegmentDAO]) -> int:
        """Count leading segments whose mounted child can be reused.

        A text segment is reusable at the same index regardless of content —
        the part updates in place, which is what keeps the growing streaming
        tail from being remounted 30 times a second. A mermaid segment is
        reusable only when its source is byte-identical, so a mounted card
        never re-runs ``Syntax`` highlighting or loses focus.

        WHO: ``reconcile_segments`` calls it to size the surviving prefix.
        WHEN: Once at the start of every reconciliation transaction.

        Args:
            segments (list[AnswerSegmentDAO]): The fresh ordered parts.

        Returns:
            int: Number of leading segments whose mounted child survives.
        """
        reusable: int = 0
        for old, new in zip(self._mounted_segments, segments):
            if old.kind != new.kind:
                break
            if new.kind == "mermaid" and old.content != new.content:
                break
            reusable += 1
        return reusable

    def _build_segment_child(self, *, segment: AnswerSegmentDAO) -> Widget:
        """Build one child widget for one answer segment.

        WHO: ``show_answer`` (pre-mount staging) and ``reconcile_segments``
        (the mounted replacement suffix) both call it.
        WHEN: Whenever a segment has no reusable mounted child.

        Args:
            segment (AnswerSegmentDAO): The part to render.

        Returns:
            Widget: An ``AnswerMarkdownPart`` for text parts, a
                ``MermaidChartBlock`` for mermaid parts.
        """
        if segment.kind == "mermaid":
            return MermaidChartBlock(source=segment.content)
        return AnswerMarkdownPart(raw_text=segment.content)


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
        """Posted after an assistant-side surface grew, by any of three posters.

        ``AssistantStreamBlock`` (answer updates) and
        ``AssistantStreamThinkingBlock`` (reasoning updates) post it after
        their coalescing timer applies a ``Static.update``.
        ``AssistantAnswerBody._drain_reconciliations`` posts it a third time,
        after its DOM transaction rather than after an ``update``: since spec
        77 the answer surface grows by mounting children asynchronously, so
        the timer's synchronous post lands BEFORE the height changes and
        would re-scroll against a stale height. That re-post is the mechanism
        acceptance criterion 6 depends on, and
        ``test_reconciliation_posts_rendered_after_the_chart_is_mounted``
        pins it.

        The app handles the message to re-check scroll-follow: the posts land
        *after* the per-mount ``_restore_follow_after_mutation`` has already
        run, so ``max_scroll_y`` expands without a scroll-end call. This
        message lets the app schedule a scroll restoration on the next
        refresh.

        ``was_following`` carries the pre-flush (or pre-transaction) follow
        state, so the app restores scroll-end only when the viewport was at
        the bottom before the surface grew.
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
        height: auto;
    }

    AssistantStreamBlock .assistant-answer-markdown-part Heading {
        color: $md-heading;
        text-style: bold;
    }

    AssistantStreamBlock .assistant-answer-markdown-part BulletList {
        color: $text;
    }

    AssistantStreamBlock .assistant-answer-markdown-part OrderedList {
        color: $text;
    }

    AssistantStreamBlock .assistant-answer-markdown-part BlockQuote {
        color: $text;
    }

    AssistantStreamBlock .assistant-answer-markdown-part CodeBlock {
        color: $text;
        background: transparent;
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
        was_following: bool = _transcript_is_at_bottom(widget=self)
        self._flush_answer()
        if self.is_mounted:
            self.post_message(AssistantStreamBlock.Rendered(was_following=was_following))

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
        """Return only answer text for the established focused-copy action.

        Returns:
            str: This block's answer, never a reasoning segment.
        """
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
        which renders vertically padded markdown or hides itself when no
        answer text exists.
        WHO: ``_flush_answer`` calls it after accepted streamed or final text.
        WHEN: Runs at an answer render boundary.
        """
        self._answer_body.show_answer(text=self._answer_text)
