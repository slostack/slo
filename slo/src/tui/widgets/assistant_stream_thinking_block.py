"""Streaming thinking-segment widget for transcript-visible reasoning summaries."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.content import Content, Span
from textual.containers import Vertical
from textual.selection import Selection
from textual.timer import Timer
from textual.widgets import Static

from src.agents.slo_agent.message_text import merge_reasoning_delta
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.markdown_content_compiler import (
    MarkdownContentCompiler,
    MarkdownContentDAO,
    _resolve_semantic_spans,
)

__all__ = ["AssistantStreamThinkingBlock"]

_STREAM_FLUSH_INTERVAL_SECONDS: float = 1.0 / 30.0
"""Coalescing cadence for streamed thinking renders (~30 fps)."""


class AssistantThinkingBody(Static):
    """Thinking-only body whose compiled visible Markdown stays selectable.

    WHAT: Compiles the stabilized raw segment through Textual ``Content`` and
    serves the visible buffer to native selection. ``Content`` supplies
    truthful per-cell visible offsets and native selection paint.
    WHO: ``AssistantStreamThinkingBlock`` owns one instance as ``_body``;
    ``Screen.get_selected_text`` queries it after a mouse selection.
    WHEN: Updated at every thinking render boundary; queried whenever the
    screen extracts selected text.
    """

    def __init__(self, *, classes: Optional[str] = None) -> None:
        """Initialise an empty thinking surface.

        Args:
            classes (Optional[str]): Space-separated CSS classes.
        """
        super().__init__(content="", classes=classes)
        self._raw_markdown: str = ""
        self._visible_text: str = ""

    def set_source_text(self, *, text: str) -> None:
        """Store and render the stabilized reasoning selection buffer.

        WHAT: Records the same unescaped reasoning buffer that Textual
        ``Content`` renders, so selection offsets index it directly.
        WHO: ``AssistantStreamThinkingBlock._render_thinking`` calls it at
        every thinking render boundary.
        WHEN: After thinking stabilization and before visibility is updated.

        Args:
            text (str): Stabilized raw Markdown to compile for the body.
        """
        self._raw_markdown = text
        compilation = MarkdownContentCompiler.compile(raw_markdown=text)
        self._visible_text = compilation.visible_text
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
        """Return the selected slice of the visible reasoning buffer.

        WHAT: Serves the raw (unescaped) reasoning text through Textual's
        documented custom-widget selection seam so a mouse drag over the
        thinking surface yields the reasoning itself.
        WHO: ``Screen.get_selected_text`` calls it for every widget captured
        by a mouse selection.
        WHEN: After a drag selection starts, moves, or completes.

        Args:
            selection (Selection): The selected range in content coordinates.

        Returns:
            Optional[tuple[str, str]]: Extracted visible reasoning text and its line
                ending, or ``None`` when no reasoning text exists.
        """
        if not self._visible_text:
            return None
        return selection.extract(self._visible_text), "\n"


class AssistantStreamThinkingBlock(Vertical):
    """Render one chronological thinking segment of an assistant turn.

    WHAT: Own one reasoning buffer, its punctuation-aware merge and markdown
    stabilization, expansion state, and a coalesced rendering timer.
    WHO: ``TranscriptProjector`` mounts and updates this widget for one segment;
    ``SloTUI`` consumes its shared rendered notification for scroll follow.
    WHEN: Mounted on the first non-empty ``thinking_delta`` for a segment and
    sealed by its matching normalized ``thinking_end`` or terminal run
    treatment. It owns no answer, terminal note, segment allocation, or
    copy-header behavior.
    """

    can_focus: bool = True

    DEFAULT_CSS = """
    AssistantStreamThinkingBlock {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        background: transparent;
    }

    AssistantStreamThinkingBlock .assistant-thinking-body {
        color: $thinking-text;
        text-style: italic;
        background: transparent;
    }
    """

    def __init__(self, *, force_expanded: Optional[bool] = None) -> None:
        """Build an empty segment with a valid body before parent mount.

        WHAT: Constructs the single ``Static`` body and all segment-local state.
        WHO: ``SloTUI.mount_thinking_block`` constructs normal live/replay blocks.
        WHEN: Runs before Textual composes the parent; initial body construction
        avoids the mount-cycle rendering race documented in ``UserMessageBlock``.

        Args:
            force_expanded (Optional[bool]): Initial global expansion state.
                ``None``/``True`` show present reasoning; ``False`` retains but
                hides it. Defaults to None.
        """
        super().__init__()
        self._expanded: bool = True if force_expanded is None else force_expanded
        self._body: AssistantThinkingBody = AssistantThinkingBody(classes="assistant-thinking-body")
        self._body.display = False
        self._thinking_text: str = ""
        self._finalized: bool = False
        self._dirty: bool = False
        self._last_rendered: str = ""
        self._flush_timer: Optional[Timer] = None

    def compose(self) -> ComposeResult:
        """Yield the segment's sole thinking body.

        WHAT: Defines the widget tree for this presentation component.
        WHO: Textual calls it during mount.
        WHEN: Once per widget mount, after construction and before streaming.

        Yields:
            ComposeResult: The single thinking ``Static``.
        """
        yield self._body

    def on_unmount(self) -> None:
        """Flush and stop the segment timer before Textual removes the block.

        WHAT: Prevents a timer from outliving this widget and preserves a pending
        last frame.
        WHO: Textual invokes it during eviction, clear, or normal unmount.
        WHEN: Exactly once when the widget leaves the mounted transcript tree.
        """
        self._stop_flush_timer()

    @property
    def thinking_text(self) -> str:
        """Return this segment's accumulated reasoning text.

        WHAT: Exposes the stabilized reasoning buffer used for rendering and copy.
        WHO: Projector and widget tests assert against it; the production
            focused-copy path reads the same buffer through ``get_copyable_text``.
        WHEN: After deltas, repairs, or sealing, whenever a test inspects state.

        Returns:
            str: Stabilized reasoning text used by focused copy and tests.
        """
        return self._thinking_text

    @property
    def finalized(self) -> bool:
        """Return whether this thinking segment is settled.

        WHAT: Exposes whether the segment may still receive a later repair.
        WHO: ``SloTUI._is_block_live`` calls it during transcript-window eviction.
        WHEN: Read after mounts and during every window-enforcement pass.

        Returns:
            bool: True once a repair or terminal sweep seals the segment.
        """
        return self._finalized

    def append_thinking(self, *, delta: str) -> None:
        """Merge one visible reasoning delta and schedule a coalesced render.

        WHAT: Applies the extracted punctuation-aware delta merge, then marks the
        segment dirty.
        WHO: ``TranscriptProjector`` calls it from a non-empty ``thinking_delta``.
        WHEN: Only while this widget remains unsealed; the projector identifies
        it by normalized ``block_id`` rather than iteration.

        Args:
            delta (str): Incremental reasoning fragment.
        """
        if self._finalized or not delta:
            return
        merged_text: str = merge_reasoning_delta(existing=self._thinking_text, delta=delta)
        self._thinking_text = self._stabilize_raw_thinking(text=merged_text)
        self._schedule_render()

    def set_thinking(self, *, content: str) -> None:
        """Replace partial text with completed reasoning truth.

        WHAT: Renders completed reasoning for an open segment.
        WHO: ``TranscriptProjector`` calls it for a matching repair
            ``thinking_end`` and for replay, in both cases before the segment
            is sealed.
        WHEN: Only while the segment is open; a contentless implicit close
            leaves the segment open so its repair can still land, and a
            sealed segment rejects late or duplicate completed text.

        Args:
            content (str): Completed visible reasoning summary.
        """
        if self._finalized or not content:
            return
        self._thinking_text = self._stabilize_raw_thinking(text=content)
        self._dirty = True
        self._flush()

    def seal(self) -> None:
        """Finalize this segment without losing accumulated reasoning.

        WHAT: Stops future deltas and completed-text replacements, and
            flushes the final pending frame.
        WHO: ``TranscriptProjector`` calls it after a completed repair, at a
            parent terminal sweep, or immediately after replay initialization.
        WHEN: Never merely because another iteration or an answer/tool event
            arrives; a contentless end leaves this segment open for its
            repair.
        """
        if self._finalized:
            return
        self._finalized = True
        self._stop_flush_timer()

    def set_expanded(self, *, expanded: bool) -> None:
        """Apply the app-wide expand/collapse state without mutating text.

        WHAT: Re-renders visibility for the stored reasoning text.
        WHO: ``SloTUI._apply_global_expand_state`` discovers this method.
        WHEN: The operator presses the established expand/collapse binding.

        Args:
            expanded (bool): True displays available reasoning; False hides it.
        """
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._render_thinking()

    def get_copyable_text(self) -> str:
        """Return reasoning-only text for the existing focused-copy path.

        WHAT: Hands the clipboard tier this segment's reasoning and nothing
            else; answer text lives on the sibling answer block.
        WHO: ``SloTUI._focused_block_text`` discovers it via the
            ``get_copyable_text`` protocol when this block holds focus.
        WHEN: The operator invokes the established copy-visible-text binding.

        Returns:
            str: This block's reasoning text, with no answer concatenation.
        """
        return self.visible_thinking_text

    @property
    def visible_thinking_text(self) -> str:
        """Return the thinking body's compiler-emitted visible text."""
        return self._body._visible_text

    def get_raw_markdown_for_copy(self) -> str:
        """Return stripped then stabilized raw Markdown for raw-copy."""
        return self._thinking_text

    def _schedule_render(self) -> None:
        """Choose immediate unmounted rendering or mounted timer coalescing.

        WHAT: Makes test/direct-construction updates synchronous and live updates
        bounded to the configured frame cadence.
        WHO: ``append_thinking`` calls it after accepting a delta.
        WHEN: Once per accepted streamed delta.
        """
        self._dirty = True
        if not self.is_mounted:
            self._flush()
            return
        self._ensure_flush_timer()

    def _ensure_flush_timer(self) -> None:
        """Start this segment's timer when a mounted dirty segment needs one.

        WHAT: Creates at most one interval timer for the current open widget.
        WHO: ``_schedule_render`` calls it only for mounted deltas.
        WHEN: The first delta after mount; no timer is started after sealing.
        """
        if self._flush_timer is not None or self._finalized:
            return
        self._flush_timer = self.set_interval(
            interval=_STREAM_FLUSH_INTERVAL_SECONDS,
            callback=self._flush,
            name="assistant-thinking-flush",
        )

    def _stop_flush_timer(self) -> None:
        """Flush pending text and tear down this segment's timer.

        WHAT: Guarantees the final dirty frame renders before the timer stops.
        WHO: ``seal`` and Textual ``on_unmount`` call it.
        WHEN: At every segment terminal boundary.
        """
        self._flush()
        if self._flush_timer is None:
            return
        self._flush_timer.stop()
        self._flush_timer = None

    def _flush(self) -> None:
        """Render changed text and post the established follow notification.

        WHAT: Performs at most one actual ``Static.update`` for a changed buffer.
        WHO: The segment timer, eager completed-text update, and terminal paths call it.
        WHEN: At the coalescing cadence or an explicit completion/seal boundary.
        """
        if not self._dirty:
            return
        self._dirty = False
        if self._thinking_text == self._last_rendered:
            return
        was_following: bool = self._check_app_at_bottom()
        self._last_rendered = self._thinking_text
        self._render_thinking()
        if self.is_mounted:
            self.post_message(AssistantStreamBlock.Rendered(was_following=was_following))

    def _check_app_at_bottom(self) -> bool:
        """Read the optional app follow snapshot without importing ``SloTUI``.

        Returns:
            bool: True when the mounted app reports transcript follow mode.
        """
        if not self.is_mounted:
            return False
        check = getattr(self.app, "_transcript_is_at_bottom", None)
        if check is None:
            return False
        return bool(check())

    def _render_thinking(self) -> None:
        """Render stabilized reasoning and apply current expansion visibility.

        WHAT: Updates only this widget's body with muted italic compiler-visible
        ``Content``. Named
        ``_render_thinking`` rather than ``_render`` because Textual's
        ``Widget._render`` hook owns the plain name on every widget.
        WHO: ``_flush`` and ``set_expanded`` call it.
        WHEN: After a changed buffer flush or expansion-state transition.
        """
        if not self._thinking_text.strip():
            self._body.set_source_text(text="")
            self._body.update("")
            self._body.display = False
            return
        self._body.set_source_text(text=self._thinking_text)
        self._body.display = self._expanded

    @classmethod
    def _stabilize_raw_thinking(cls, *, text: str) -> str:
        """Strip and stabilize the sole raw-thinking truth at every mutation boundary."""
        return cls._stabilize_reasoning_markdown(text=text.strip())

    @classmethod
    def _stabilize_reasoning_markdown(cls, *, text: str) -> str:
        """Normalize the extracted streamed-reasoning markdown glitches.

        Args:
            text (str): Raw accumulated reasoning text.

        Returns:
            str: Line-normalized Markdown source used for both rendering and selection.
        """
        normalized_lines: list[str] = []
        for line in text.splitlines():
            normalized_lines.append(cls._normalize_reasoning_line(line=line))
        return "\n".join(normalized_lines)

    @staticmethod
    def _normalize_reasoning_line(*, line: str) -> str:
        """Normalize one malformed streamed emphasis line.

        Args:
            line (str): One raw reasoning line.

        Returns:
            str: Corrected emphasis line or the original line.
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
