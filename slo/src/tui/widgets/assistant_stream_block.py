"""Streaming assistant-turn widget for transcript-visible reasoning summaries."""

from __future__ import annotations

from typing import Optional

from rich.markdown import Markdown
from rich.padding import Padding
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.timer import Timer
from textual.widgets import Static

__all__ = ["AssistantStreamBlock"]

_STREAM_FLUSH_INTERVAL_SECONDS: float = 1.0 / 30.0
"""Coalescing cadence for streamed reasoning/answer renders (~30 fps)."""


class AssistantStreamBlock(Vertical):
    """Render one in-flight assistant turn.

    The block maintains two visible transcript regions:

    1. reasoning summary text,
    2. assistant answer text.

    The reasoning region is optional. The answer region is always present
    once answer text arrives or the final completed answer is known.
    """

    class Rendered(Message):
        """Posted after the coalescing timer flushes at least one dirty region.

        The app handles this to re-check scroll-follow: because the timer fires
        *after* the per-mount ``_restore_follow_after_mutation`` has already run,
        the ``Static.update`` inside ``_render_answer`` / ``_render_thinking``
        expands ``max_scroll_y`` without a scroll-end call. This message lets
        the app schedule a scroll restoration on the next refresh.

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
        padding: 1 1;
        background: $panel;
    }

    AssistantStreamBlock .assistant-thinking-body {
        color: $text-muted;
        text-style: italic;
        margin: 0 0 1 0;
        background: $surface;
    }

    AssistantStreamBlock .assistant-answer-body {
        color: $text;
        background: $surface;
        text-style: none;
    }

    AssistantStreamBlock .assistant-answer-body Heading {
        color: $accent;
        text-style: bold;
    }

    AssistantStreamBlock .assistant-answer-body BulletList {
        color: $text;
    }

    AssistantStreamBlock .assistant-answer-body OrderedList {
        color: $text;
    }

    AssistantStreamBlock .assistant-answer-body BlockQuote {
        color: $text;
    }

    AssistantStreamBlock .assistant-answer-body CodeBlock {
        color: $text;
        background: $surface;
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
        force_expanded: Optional[bool] = None,
    ) -> None:
        """Seed an empty assistant streaming block.

        Args:
            title_prefix (Optional[str]): When set, renders a dim single-line
                label above the block's content using the ``sub-agent-label``
                CSS class. ``None`` (default) produces no label and the block
                renders identically to the pre-feature behaviour.
            force_expanded (Optional[bool]): Initial expansion state from the
                global expand-all toggle. ``None`` (default) keeps the natural
                behaviour (reasoning shown whenever present); ``False`` hides
                the reasoning region; ``True`` shows it.
        """
        super().__init__()
        self._title_prefix: Optional[str] = title_prefix
        # The natural state shows reasoning whenever present; only an explicit
        # collapse-all (force_expanded=False) hides it.
        self._expanded: bool = True if force_expanded is None else force_expanded
        self._label: Optional[Static] = (
            Static(title_prefix, classes="sub-agent-label") if title_prefix else None
        )
        self._thinking_body: Static = Static("", classes="assistant-thinking-body")
        self._thinking_body.display = False
        self._answer_body: Static = Static("", classes="assistant-answer-body")
        self._answer_body.display = False
        self._terminal_note: Static = Static("", classes="assistant-terminal-warning")
        self._terminal_note.display = False
        self._thinking_text: str = ""
        self._answer_text: str = ""
        self._terminal_note_text: str = ""
        self._finalized: bool = False
        self._answer_dirty: bool = False
        self._thinking_dirty: bool = False
        self._last_rendered_answer: str = ""
        self._last_rendered_thinking: str = ""
        self._flush_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        """Compose the visible child widgets.

        Yields the optional label first, then the three logical transcript
        regions (thinking, answer, terminal note). Omits the label when
        ``title_prefix`` was not supplied.

        Yields:
            ComposeResult: Optional label then the three content regions.
        """
        if self._label is not None:
            yield self._label
        yield self._thinking_body
        yield self._answer_body
        yield self._terminal_note

    def on_unmount(self) -> None:
        """Flush and cancel the coalescing timer when the block leaves the DOM."""
        self._stop_flush_timer()

    def _ensure_flush_timer(self) -> None:
        """Start the coalescing timer on the first streamed delta, if mounted.

        Called by the schedulers. No-op when unmounted (the scheduler renders
        synchronously instead), when already running, or once finalized.
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
        """Render whichever streamed surfaces changed since the last tick.

        The ~30 fps ``set_interval`` callback and the only place a mounted block
        calls into the real render methods, so per-frame render cost is bounded
        to one answer render and one reasoning render regardless of delta count.
        Posts ``AssistantStreamBlock.Rendered`` when mounted and at least one
        surface was dirty, carrying the pre-flush follow state so the app can
        restore scroll-end after the ``Static.update`` expands ``max_scroll_y``.
        """
        if not self._answer_dirty and not self._thinking_dirty:
            return
        was_following: bool = self._check_app_at_bottom()
        if self._answer_dirty:
            self._flush_answer()
        if self._thinking_dirty:
            self._flush_thinking()
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

    def _flush_thinking(self) -> None:
        """Render the accumulated reasoning, skipping work when text is unchanged.

        Tracks text only — visibility is handled by ``set_expanded``, which
        calls ``_render_thinking`` directly and deliberately bypasses the flusher.
        Clears the thinking dirty flag and re-renders only when the accumulated
        text differs from the last rendered snapshot.
        """
        self._thinking_dirty = False
        if self._thinking_text == self._last_rendered_thinking:
            return
        self._last_rendered_thinking = self._thinking_text
        self._render_thinking()

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

    def _schedule_thinking_render(self) -> None:
        """Mark the reasoning dirty; render now when unmounted, else coalesce.

        Called by ``append_thinking``. Mirrors ``_schedule_answer_render`` for
        the reasoning surface: synchronous when unmounted, coalesced once
        mounted.
        """
        self._thinking_dirty = True
        if not self.is_mounted:
            self._flush_thinking()
            return
        self._ensure_flush_timer()

    @property
    def thinking_text(self) -> str:
        """Return the accumulated visible reasoning summary text.

        Returns:
            str: Accumulated reasoning text.
        """
        return self._thinking_text

    @property
    def answer_text(self) -> str:
        """Return the accumulated visible answer text.

        Returns:
            str: Accumulated answer text.
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
        """Return the visible assistant text for clipboard copy.

        Combines reasoning summary and answer text with a blank line
        separator when both are present. Called by
        ``SloTUI.action_copy_visible_text`` when this block holds focus.

        Returns:
            str: Reasoning + answer text joined by a blank line, or just
                whichever part is non-empty.
        """
        parts: list[str] = [p for p in (self._thinking_text, self._answer_text) if p]
        return "\n\n".join(parts)

    def set_expanded(self, *, expanded: bool) -> None:
        """Set the expansion state from the global expand-all toggle.

        Only the reasoning region is gated; the answer is always shown. A
        re-render re-evaluates reasoning visibility against the new state.

        Args:
            expanded (bool): True shows reasoning when present; False hides it.
        """
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._render_thinking()

    def append_thinking(self, *, delta: str) -> None:
        """Append visible reasoning summary text.

        Args:
            delta (str): Incremental visible reasoning summary text.
        """
        if self._finalized or not delta:
            return
        self._thinking_text = self._merge_reasoning_delta(
            existing=self._thinking_text,
            delta=delta,
        )
        self._schedule_thinking_render()

    def set_thinking(self, *, content: str) -> None:
        """Replace the visible reasoning summary with completed truth.

        Args:
            content (str): Completed visible reasoning summary text.
        """
        if self._finalized or not content:
            return
        self._thinking_text = content
        self._thinking_dirty = True
        self._flush_thinking()

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
        from accepting further ``append_text`` / ``append_thinking`` deltas
        while preserving whatever was already streamed into the answer and
        reasoning regions. Flushes pending dirty regions before stopping the
        timer so the last streamed delta is always on screen.
        """
        if self._finalized:
            return
        self._finalized = True
        self._stop_flush_timer()

    def _render_thinking(self) -> None:
        """Render the current reasoning summary with Pi-style padding.

        Reasoning text is already semantically distinct from answer text,
        so Slo does not prepend a redundant literal "Thinking" label.
        It is rendered as muted italic markdown with horizontal padding.
        """
        if not self._thinking_text.strip():
            self._thinking_body.update("")
            self._thinking_body.display = False
            return
        # Keep the content current even while hidden, so a later expand-all
        # reveals the full reasoning without a re-render gap. Visibility is
        # gated by the global expand-all state.
        self._thinking_body.update(
            Padding(
                Markdown(
                    self._stabilize_reasoning_markdown(text=self._thinking_text.strip()), style="italic"
                ),
                pad=(1, 1, 1, 1),
            )
        )
        self._thinking_body.display = self._expanded

    def _render_answer(self) -> None:
        """Render the current assistant answer with Pi-style padding."""
        if not self._answer_text:
            self._answer_body.update("")
            self._answer_body.display = False
            return
        self._answer_body.display = True
        self._answer_body.update(
            Padding(
                Markdown(self._escape_markdown_breakers(text=self._answer_text)),
                pad=(1, 1, 1, 1),
            )
        )

    @staticmethod
    def _escape_markdown_breakers(*, text: str) -> str:
        """Escape angle-bracket fragments that break transcript readability.

        Args:
            text (str): Raw assistant answer text.

        Returns:
            str: Stabilized markdown text.
        """
        return text.replace("<", "\\<").replace(">", "\\>")

    @classmethod
    def _stabilize_reasoning_markdown(cls, *, text: str) -> str:
        """Normalize common streamed-markdown glitches in reasoning text.

        Args:
            text (str): Raw streamed reasoning text.

        Returns:
            str: Markdown-safe reasoning text that keeps headings readable.
        """
        escaped_text: str = cls._escape_markdown_breakers(text=text)
        normalized_lines: list[str] = []
        for line in escaped_text.splitlines():
            normalized_lines.append(cls._normalize_reasoning_line(line=line))
        return "\n".join(normalized_lines)

    @staticmethod
    def _normalize_reasoning_line(*, line: str) -> str:
        """Normalize one reasoning line for markdown rendering.

        Args:
            line (str): One raw reasoning line.

        Returns:
            str: Normalized line.
        """
        stripped_line: str = line.strip()
        if (
            stripped_line.startswith("*")
            and not stripped_line.startswith("**")
            and stripped_line.endswith("**")
            and stripped_line.count("*") == 3
        ):
            return f"**{stripped_line[1:-2].strip()}**"
        if stripped_line.startswith("*") and stripped_line.endswith("*") and stripped_line.count("*") == 2:
            return f"**{stripped_line[1:-1].strip()}**"
        return line

    @staticmethod
    def _merge_reasoning_delta(*, existing: str, delta: str) -> str:
        """Append one streamed reasoning fragment with lightweight spacing repair.

        Args:
            existing (str): Previously accumulated reasoning text.
            delta (str): New streamed fragment.

        Returns:
            str: Combined reasoning text.
        """
        if not existing or not delta:
            return existing + delta
        if existing[-1].isspace() or delta[0].isspace():
            return existing + delta
        if delta[0] in ",.;:!?)]}%\"'”’" or existing[-1] in '([{$"“‘':
            return existing + delta
        if delta[0] in "-/\\_`" or existing[-1] in "-/\\_`'’":
            return existing + delta
        return f"{existing} {delta}"
