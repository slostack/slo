"""Dedicated transcript widget for one user turn."""

from __future__ import annotations

from typing import Optional

from rich.markdown import Markdown
from rich.padding import Padding
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

__all__ = ["UserMessageBlock"]

_COLLAPSED_MAX_WIDTH: int = 80
"""Maximum characters shown for the collapsed single-line summary."""


class UserMessageBlock(Vertical):
    """Render one user turn as padded markdown.

    The user-side analogue of ``AssistantStreamBlock``. It carries a single
    text buffer and re-renders only that buffer, so a user turn is a
    dedicated component rather than a flat transcript line, and the
    transcript is never reparsed as one document.
    """

    can_focus: bool = True

    DEFAULT_CSS = """
    UserMessageBlock {
        width: 100%;
        height: auto;
        margin: 1 0 1 0;
        padding: 0 0;
        background: $panel;
    }

    UserMessageBlock .user-message-body {
        color: $accent;
        text-style: bold;
        background: $panel;
    }
    """

    def __init__(self, *, text: str, force_expanded: Optional[bool] = None) -> None:
        """Seed the block with the user's submitted text.

        The visible renderable is built here, at construction, rather than
        in ``on_mount``: setting a ``Static``'s content during the parent's
        mount cycle races the child's first render and Textual raises while
        compositing. Building it up front means the ``Static`` always has a
        valid renderable before it is ever rendered.

        Args:
            text (str): The raw user prompt text.
            force_expanded (Optional[bool]): Initial expansion state from the
                global expand-all toggle. ``None`` (default) renders the
                natural full text; ``False`` collapses to a single truncated
                line; ``True`` is the full text.
        """
        super().__init__()
        self._text: str = text
        # The natural state for a user turn is the full text; only an explicit
        # collapse-all (force_expanded=False) shows the truncated summary.
        self._expanded: bool = True if force_expanded is None else force_expanded
        self._body: Static = Static(self._body_renderable(), classes="user-message-body")

    def compose(self) -> ComposeResult:
        """Compose the single visible region.

        Yields:
            ComposeResult: The user-text region.
        """
        yield self._body

    @property
    def text(self) -> str:
        """Return the raw user text.

        Returns:
            str: The user prompt text.
        """
        return self._text

    def set_expanded(self, *, expanded: bool) -> None:
        """Set the expansion state from the global expand-all toggle.

        Args:
            expanded (bool): True shows the full text; False shows the
                collapsed single-line summary.
        """
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._body.update(self._body_renderable())

    def _body_renderable(self):
        """Build the body renderable for the current expansion state.

        Returns:
            RenderableType: Full padded markdown when expanded, otherwise the
                truncated single-line summary.
        """
        if self._expanded:
            return self._renderable(text=self._text)
        return self._collapsed_renderable(text=self._text)

    @staticmethod
    def _collapsed_renderable(*, text: str):
        """Build the collapsed single-line summary for the user text.

        Args:
            text (str): The raw user prompt text.

        Returns:
            RenderableType: A padded, truncated first line, or an empty string
                when the text is blank.
        """
        stripped: str = text.strip()
        if not stripped:
            return ""
        first_line: str = stripped.split("\n")[0]
        has_more: bool = "\n" in stripped or len(first_line) > _COLLAPSED_MAX_WIDTH
        if len(first_line) > _COLLAPSED_MAX_WIDTH:
            first_line = first_line[: _COLLAPSED_MAX_WIDTH - 3] + "..."
        elif has_more:
            first_line = f"{first_line} …"
        return Padding(first_line, pad=(0, 1, 0, 1))

    def get_copyable_text(self) -> str:
        """Return the raw user prompt text for clipboard copy.

        Called by ``SloTUI.action_copy_visible_text`` when this block holds
        focus and the user presses the copy chord.

        Returns:
            str: The full user prompt text, unmodified.
        """
        return self._text

    @staticmethod
    def _renderable(*, text: str):
        """Build the padded-markdown renderable for the user text.

        Whitespace-only text renders nothing so an empty submission does
        not leave a blank padded block in the transcript.

        Args:
            text (str): The raw user prompt text.

        Returns:
            RenderableType: Padded markdown, or an empty string when blank.
        """
        if not text.strip():
            return ""
        return Padding(Markdown(text.strip()), pad=(1, 1, 1, 1))
