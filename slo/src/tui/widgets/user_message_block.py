"""Dedicated transcript widget for one user turn."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.padding import Padding
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

__all__ = ["UserMessageBlock"]


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

    def __init__(self, *, text: str) -> None:
        """Seed the block with the user's submitted text.

        The visible renderable is built here, at construction, rather than
        in ``on_mount``: setting a ``Static``'s content during the parent's
        mount cycle races the child's first render and Textual raises while
        compositing. Building it up front means the ``Static`` always has a
        valid renderable before it is ever rendered.

        User turns are always displayed in full text; the global expand/
        collapse toggle does not affect them.

        Args:
            text (str): The raw user prompt text.
        """
        super().__init__()
        self._text: str = text
        self._expanded: bool = True
        self._body: Static = Static(self._renderable(text=self._text), classes="user-message-body")

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
        """Accept the global expand-all call without acting on it.

        User turns are always shown in full text. The global expand/collapse
        toggle applies to assistant and tool blocks only; calling this method
        on a ``UserMessageBlock`` is deliberately a no-op so the block's
        visual state is never changed by the app-wide toggle.

        Args:
            expanded (bool): Ignored. Always a no-op for user turns.
        """
        return

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
