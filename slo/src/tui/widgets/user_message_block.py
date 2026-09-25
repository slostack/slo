"""Dedicated source-faithful transcript widget for one user turn."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.content import Content
from textual.containers import Vertical
from textual.selection import Selection
from textual.widgets import Static

from src.tui.widgets.markdown_content_compiler import (
    MarkdownContentCompiler,
    _resolve_semantic_spans,
)

__all__ = ["UserMessageBlock", "UserMessageBody"]


class UserMessageBody(Static):
    """Selectable source-faithful body for one immutable user-message source buffer."""

    def __init__(self, *, source_text: str, classes: Optional[str] = None) -> None:
        """Build Content from the exact selection source before its parent mounts.

        WHAT: Stores one user source buffer and makes Textual render that exact
        string with presentation-only source spans.
        WHO: ``UserMessageBlock`` creates its sole body during construction.
        WHEN: Before parent mount, avoiding the child-mount render race.

        Args:
            source_text (str): Exact submitted, steering, or replayed user source.
            classes (Optional[str]): Optional CSS classes for the body widget.
        """
        self._raw_markdown: str = source_text
        compilation = MarkdownContentCompiler.compile(raw_markdown=source_text)
        self._visible_text: str = compilation.visible_text
        self._semantic_spans = compilation.spans
        super().__init__(content=Content(text=self._visible_text), classes=classes)

    def on_mount(self) -> None:
        """Resolve compiler role spans only after the mounted app supplies its theme."""
        self.update(
            Content(
                text=self._visible_text,
                spans=list(
                    _resolve_semantic_spans(
                        spans=self._semantic_spans,
                        theme_variables=self.app.current_theme.variables,
                    )
                ),
            )
        )

    def get_selection(self, selection: Selection) -> Optional[tuple[str, str]]:
        """Extract a native selection directly from the exact rendered source buffer.

        WHAT: Returns a bounded or whole-source range without offset mapping or
        clipboard behavior.
        WHO: Textual ``Screen`` calls this through its standard selection path.
        WHEN: After a user-message body becomes the selected widget.

        Args:
            selection (Selection): Native Textual selection for this body.

        Returns:
            Optional[tuple[str, str]]: Extracted raw text plus newline separator,
            or None when the source is empty.
        """
        if not self._visible_text:
            return None
        return selection.extract(self._visible_text), "\n"


class UserMessageBlock(Vertical):
    """Render one source-faithful user turn in the transcript user band."""

    can_focus: bool = True

    DEFAULT_CSS = """
    UserMessageBlock {
        width: 100%;
        height: auto;
        margin: 1 0 1 0;
        padding: 1 1 2 1;
        background: $user-msg-bg;
        align-vertical: middle;
    }

    UserMessageBlock .user-message-body {
        width: 100%;
        height: auto;
        color: $text;
        text-style: bold;
        text-align: left;
        background: $user-msg-bg;
    }
    """

    def __init__(self, *, text: str) -> None:
        """Store and render the exact submitted user-message source.

        WHAT: Builds the child Content visual from the same string used for
        focused copy and native range extraction.
        WHO: ``SloTUI`` mounts this through ``TranscriptProjector`` for live,
        steering, and replayed user turns.
        WHEN: Before parent mount, avoiding the existing child-mount render race.

        Args:
            text (str): Exact user-message source; never stripped or transformed.
        """
        super().__init__()
        self._text: str = text
        self._expanded: bool = True
        self._body: UserMessageBody = UserMessageBody(
            source_text=self._text,
            classes="user-message-body",
        )

    def compose(self) -> ComposeResult:
        """Compose the sole user-message source-faithful body.

        Yields:
            ComposeResult: The body built from the exact user source buffer.
        """
        yield self._body

    @property
    def text(self) -> str:
        """Return the exact raw user text retained for render and full-block copy.

        Returns:
            str: The unmodified user prompt, steering, or replay source.
        """
        return self._text

    def set_expanded(self, *, expanded: bool) -> None:
        """Accept the global expand-all call without changing an always-full user turn.

        Args:
            expanded (bool): Ignored because user turns never collapse.
        """
        return

    def get_copyable_text(self) -> str:
        """Return complete visible user text for the focused-copy funnel.

        Returns:
            str: Full rendered user text, distinct from a bounded mouse selection.
        """
        return self._body._visible_text

    def get_raw_markdown_for_copy(self) -> str:
        """Return the exact complete raw Markdown for the raw-copy action."""
        return self._text
