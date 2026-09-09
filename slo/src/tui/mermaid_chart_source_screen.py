"""Full-screen, read-only view of one mermaid chart's source."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import TextArea

from src.tui.widgets.literal_text_static import LiteralTextStatic

__all__ = ["MermaidChartSourceScreen"]


class MermaidChartSourceScreen(ModalScreen[None]):
    """Full-screen, read-only, scrollable view of one chart's source.

    WHAT: Hosts a read-only ``TextArea`` (native scroll and native text
    selection) with the verbatim mermaid source, plus a title and a controls
    line. Parallel to ``GitDiffScreen``: the two share the modal-screen
    pattern, not code.
    WHO: ``SloTUI`` pushes it via non-waiting ``push_screen`` from the
        message handler (``push_screen_wait`` is worker-only in Textual 8.2.8).
    WHEN: While the user inspects a chart full-screen; ``Esc`` dismisses.
    """

    DEFAULT_CSS = """
    MermaidChartSourceScreen { layout: vertical; }
    MermaidChartSourceScreen .mermaid-source-title {
        width: 100%; height: auto; padding: 0 1;
        color: $text-muted; border-bottom: solid $accent;
    }
    MermaidChartSourceScreen .mermaid-source-controls {
        width: 100%; height: auto; padding: 0 1; color: $text-muted;
    }
    MermaidChartSourceScreen #mermaid-source-area { width: 100%; height: 1fr; }
    """

    BINDINGS = [
        Binding(key="escape", action="dismiss", description="close"),
    ]

    def __init__(self, *, source: str, directive: str) -> None:
        """Accept the chart's source and directive for display.

        Args:
            source (str): Verbatim mermaid source (full, never truncated).
            directive (str): Directive line shown in the title.
        """
        super().__init__()
        self._source: str = source
        self._directive: str = directive

    def compose(self) -> ComposeResult:
        """Mount the title, controls line, and the read-only source area.

        WHAT: Builds the modal's three regions from the constructor arguments.
        WHO: Textual calls it when the app pushes this screen.
        WHEN: Once per screen push.

        Yields:
            ComposeResult: Title, controls, and the read-only text area.
        """
        yield LiteralTextStatic(f"📊 Mermaid chart — {self._directive}", classes="mermaid-source-title")
        yield LiteralTextStatic(
            "read-only source · drag to select · Esc close", classes="mermaid-source-controls"
        )
        yield TextArea(text=self._source, read_only=True, id="mermaid-source-area")

    async def action_dismiss(self, result: None = None) -> None:
        """Dismiss the mermaid source screen when the operator presses Escape.

        WHAT: Closes this modal and returns control to the transcript without
            mutating the chart source or transcript state. Implemented
            explicitly (the ``GitDiffScreen.action_dismiss`` precedent,
            ``src/tui/git_diff_screen.py:75``) so the dismissal contract is
            visible, documented, and pinned by test.
        WHO: Textual invokes it for the screen's ``escape`` binding — the
            focused ``TextArea`` defines no ``escape`` binding, so the key
            bubbles to the screen (verified by pilot).
        WHEN: While a user is inspecting a mermaid chart source full-screen.

        Args:
            result (None, optional): Modal result required by the Screen action
                signature. Defaults to None.
        """
        await self.dismiss(result)
