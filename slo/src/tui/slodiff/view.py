"""Clean-room Textual diff widget with no imports from the Slo integration layer."""

from __future__ import annotations

import asyncio
import difflib
from typing import Iterator, Optional, TYPE_CHECKING, TypeVar

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, HorizontalScroll, Vertical
from textual.content import Content, Span
from textual.highlight import guess_language, highlight
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from .model import DiffOpcodeDAO, SloDiffModel

_T = TypeVar("_T")


class _SyncedScroll(HorizontalScroll):
    """Mirror horizontal scroll offset to the other split pane."""

    def __init__(self, *children: Widget, id: Optional[str] = None, classes: Optional[str] = None) -> None:
        """Create an unlinked horizontal pane until the view composes both panes."""
        super().__init__(*children, id=id, classes=classes)
        self.link: Optional[_SyncedScroll] = None

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        """Synchronize x-offset whenever Textual scrolls this pane."""
        if self.link is None or self.link.scroll_x == new_value:
            return
        self.link.scroll_x = new_value

    def set_scroll_x(self, *, offset: float) -> None:
        """Set one public scroll offset and mirror it to the linked split pane.

        WHAT: Gives SloDiffView a deterministic public synchronization seam.
        WHO: Textual scroll input and SloDiffView tests use this pane operation.
        WHEN: Called whenever an operator scrolls a split diff column horizontally.

        Args:
            offset (float): Desired horizontal offset for both columns.
        """
        self.scroll_to(x=offset, animate=False, force=True)


class SloDiffView(Container):
    """Render extractable split or unified text differences from two strings."""

    DEFAULT_CSS = """
    SloDiffView { width: 100%; height: 1fr; }
    SloDiffView .diff-added { color: $text; background: $success 25%; }
    SloDiffView .diff-removed { color: $text; background: $error 25%; }
    SloDiffView .diff-context { color: $foreground; }
    SloDiffView .diff-separator { color: $accent; text-style: dim; }
    SloDiffView .diff-column { width: 1fr; height: 1fr; overflow-x: auto; }
    SloDiffView .diff-column-content { width: auto; min-width: 100%; height: auto; }
    SloDiffView .diff-row { width: auto; min-width: 100%; }
    """

    _SPLIT_MIN_WIDTH: int = 120
    split: reactive[bool] = reactive(False, recompose=True)
    wrap: reactive[bool] = reactive(False, recompose=True)
    annotations: reactive[bool] = reactive(True, recompose=True)

    def __init__(
        self,
        *,
        base_content: str,
        changed_content: str,
        language_hint: Optional[str] = None,
        path_hint: Optional[str] = None,
        classes: Optional[str] = None,
        id: Optional[str] = None,
    ) -> None:
        """Store raw content and caller-provided syntax hints before model preparation.

        Args:
            base_content (str): Original text for the left or removed side.
            changed_content (str): Worktree text for the right or added side.
            language_hint (Optional[str]): Explicit Textual lexer name. Defaults to None.
            path_hint (Optional[str]): File path used by Textual language detection. Defaults to None.
            classes (Optional[str]): Optional CSS classes. Defaults to None.
            id (Optional[str]): Optional widget identifier. Defaults to None.
        """
        super().__init__(classes=classes, id=id)
        self._base_content: str = base_content
        self._changed_content: str = changed_content
        self._language_hint: Optional[str] = language_hint
        self._path_hint: Optional[str] = path_hint
        self._model: Optional[SloDiffModel] = None
        self._language: Optional[str] = None

    async def on_mount(self) -> None:
        """Select an initial layout and prepare the model without blocking the event loop."""
        self._disable_split_when_terminal_is_narrow()
        await self.prepare()

    def _disable_split_when_terminal_is_narrow(self) -> None:
        """Keep side-by-side mode off when the terminal cannot show two useful panes.

        WHAT: Preserves the unified default on narrow terminals even when a caller
            selected split mode before the widget mounted.
        WHO: ``on_mount`` calls this before preparing the first rendered diff.
        WHEN: Runs once when Textual assigns the initial terminal size.
        """
        if self.app.size.width < self._SPLIT_MIN_WIDTH:
            self.split = False

    async def prepare(self) -> None:
        """Build the pure model in a worker thread before recomposing visible rows."""
        from .model import SloDiffModel

        self._model = await asyncio.to_thread(
            SloDiffModel.build,
            base_content=self._base_content,
            changed_content=self._changed_content,
        )
        self._language = self._resolve_language()
        self.refresh(recompose=True)

    def _resolve_language(self) -> Optional[str]:
        """Resolve only an explicit or path-derived lexer, otherwise preserve literal text.

        Content-only guessing is deliberately excluded: Textual 8.2.8 classifies Python
        text with an empty path as ``teratermmacro``. The Slo integration supplies the
        validated repository-relative path, while extractable callers may use either hint.

        Returns:
            Optional[str]: A deliberate lexer name, or None for safe plain text.
        """
        if self._language_hint:
            return self._language_hint
        if not self._path_hint:
            return None
        return guess_language(code=self._changed_content or self._base_content, path=self._path_hint)

    def compose(self) -> ComposeResult:
        """Compose loading, split, or unified children for the current reactive state."""
        if self._model is None:
            yield Static("Loading diff…", markup=False, classes="diff-separator")
            return
        if self.split:
            yield from self._compose_split()
            return
        yield from self._compose_unified()

    @staticmethod
    def _loop_last(*, items: list[_T]) -> Iterator[tuple[bool, _T]]:
        """Yield each item with a final-item flag without private Textual helpers."""
        for index, item in enumerate(items):
            yield index == len(items) - 1, item

    @staticmethod
    def _char_spans_for_pair(*, old_line: str, new_line: str) -> list[Span]:
        """Return changed new-text character spans for matched replacement rows."""
        matcher = difflib.SequenceMatcher(a=old_line, b=new_line, autojunk=False)
        return [
            Span(start=j1, end=j2, style="diff-added")
            for tag, _i1, _i2, j1, j2 in matcher.get_opcodes()
            if tag in ("replace", "insert") and j2 > j1
        ]

    @staticmethod
    def _iter_line_pairs(
        *, old_lines: list[str], new_lines: list[str]
    ) -> Iterator[tuple[Optional[str], Optional[str]]]:
        """Yield padded old/new rows so split changed blocks retain alignment."""
        for index in range(max(len(old_lines), len(new_lines))):
            old_line: Optional[str] = old_lines[index] if index < len(old_lines) else None
            new_line: Optional[str] = new_lines[index] if index < len(new_lines) else None
            yield old_line, new_line

    @staticmethod
    def _annotation_symbol(*, role: str) -> str:
        """Map a rendering role to its accessible stable text prefix."""
        if role == "added":
            return "+ "
        if role == "removed":
            return "- "
        return "  "

    def _render_code_line(self, *, text: str, role: str, char_spans: Optional[list[Span]] = None) -> Static:
        """Create one syntax-highlighted, literal diff row during composition."""
        content: Content = highlight(code=text, language=self._language, path=self._path_hint)
        if char_spans:
            for char_span in char_spans:
                content = content.stylize_before(
                    char_span.style,
                    start=char_span.start,
                    end=char_span.end,
                )
        if self.annotations:
            content = Content(self._annotation_symbol(role=role)).append(content)
        row = Static(content, markup=False, classes=f"diff-{role} diff-row")
        row.styles.text_wrap = "wrap" if self.wrap else "nowrap"
        return row

    def _compose_unified(self) -> ComposeResult:
        """Render changed hunks as one ordered column for narrow terminals."""
        assert self._model is not None
        for is_last, hunk in self._loop_last(items=self._model.hunks):
            for opcode in hunk.opcodes:
                yield from self._unified_rows_for_opcode(opcode=opcode)
            if not is_last:
                yield Static("⋮", markup=False, classes="diff-separator")

    def _unified_rows_for_opcode(self, *, opcode: DiffOpcodeDAO) -> ComposeResult:
        """Translate one opcode into context, removed, and added unified rows."""
        assert self._model is not None
        if opcode.tag == "equal":
            for text in self._model.base_lines[opcode.base_start : opcode.base_end]:
                yield self._render_code_line(text=text.rstrip("\n"), role="context")
            return
        for text in self._model.base_lines[opcode.base_start : opcode.base_end]:
            yield self._render_code_line(text=text.rstrip("\n"), role="removed")
        for text in self._model.changed_lines[opcode.changed_start : opcode.changed_end]:
            yield self._render_code_line(text=text.rstrip("\n"), role="added")

    def _compose_split(self) -> ComposeResult:
        """Render horizontally synchronized base and changed columns on wide terminals."""
        assert self._model is not None
        left_rows: list[Static] = []
        right_rows: list[Static] = []
        for is_last, hunk in self._loop_last(items=self._model.hunks):
            for opcode in hunk.opcodes:
                self._append_split_opcode(opcode=opcode, left_rows=left_rows, right_rows=right_rows)
            if not is_last:
                left_rows.append(Static("⋮", markup=False, classes="diff-separator"))
                right_rows.append(Static("⋮", markup=False, classes="diff-separator"))
        left_column = Vertical(*left_rows, classes="diff-column-content")
        right_column = Vertical(*right_rows, classes="diff-column-content")
        left_pane = _SyncedScroll(left_column, id="slodiff-left", classes="diff-column")
        right_pane = _SyncedScroll(right_column, id="slodiff-right", classes="diff-column")
        left_pane.link = right_pane
        right_pane.link = left_pane
        with Horizontal():
            yield left_pane
            yield right_pane

    def _append_split_opcode(
        self,
        *,
        opcode: DiffOpcodeDAO,
        left_rows: list[Static],
        right_rows: list[Static],
    ) -> None:
        """Append aligned base and changed widgets for one grouped opcode."""
        assert self._model is not None
        old_lines = [
            text.rstrip("\n") for text in self._model.base_lines[opcode.base_start : opcode.base_end]
        ]
        new_lines = [
            text.rstrip("\n") for text in self._model.changed_lines[opcode.changed_start : opcode.changed_end]
        ]
        if opcode.tag == "equal":
            left_rows.extend(self._render_code_line(text=text, role="context") for text in old_lines)
            right_rows.extend(self._render_code_line(text=text, role="context") for text in new_lines)
            return
        paired_replacement: bool = opcode.tag == "replace" and len(old_lines) == len(new_lines)
        for old_line, new_line in self._iter_line_pairs(old_lines=old_lines, new_lines=new_lines):
            self._append_split_pair(
                old_line=old_line,
                new_line=new_line,
                paired_replacement=paired_replacement,
                left_rows=left_rows,
                right_rows=right_rows,
            )

    def _append_split_pair(
        self,
        *,
        old_line: Optional[str],
        new_line: Optional[str],
        paired_replacement: bool,
        left_rows: list[Static],
        right_rows: list[Static],
    ) -> None:
        """Append one aligned changed-row pair, including inline spans when applicable."""
        left_rows.append(
            Static("", markup=False, classes="diff-context")
            if old_line is None
            else self._render_code_line(text=old_line, role="removed")
        )
        if new_line is None:
            right_rows.append(Static("", markup=False, classes="diff-context"))
            return
        spans: Optional[list[Span]] = (
            self._char_spans_for_pair(old_line=old_line, new_line=new_line)
            if paired_replacement and old_line is not None
            else None
        )
        right_rows.append(self._render_code_line(text=new_line, role="added", char_spans=spans))
