"""Focused screen that hosts slodiff over the Slo transcript."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen

from src.tui.git_diff_content_service import GitDiffContentDAO
from src.tui.slodiff.model import SloDiffModel
from src.tui.slodiff.view import SloDiffView
from src.tui.widgets.literal_text_static import LiteralTextStatic


class GitDiffScreen(Screen[None]):
    """Host one validated slodiff view and its screen-level keyboard policy."""

    DEFAULT_CSS = """
    GitDiffScreen { layout: vertical; }
    GitDiffScreen .git-diff-summary { width: 100%; height: auto; padding: 0 1; color: $text-muted; border-bottom: solid $accent; }
    GitDiffScreen .git-diff-controls { width: 100%; height: auto; padding: 0 1; color: $text-muted; }
    GitDiffScreen #git-diff-scroll { width: 100%; height: 1fr; overflow-x: auto; overflow-y: auto; }
    GitDiffScreen .git-diff-view { width: 100%; height: auto; }
    """

    BINDINGS = [
        Binding(key="escape", action="dismiss", description="close"),
        Binding(key="s", action="toggle_split", description="side-by-side"),
        Binding(key="w", action="toggle_wrap", description="wrap lines"),
        Binding(key="a", action="toggle_annotations", description="show gutters"),
    ]

    def __init__(self, *, content: GitDiffContentDAO) -> None:
        """Accept prevalidated content from the application screen-opening path.

        Args:
            content (GitDiffContentDAO): HEAD/worktree content already loaded by the service.
        """
        super().__init__()
        self._content: GitDiffContentDAO = content
        self._view: SloDiffView = SloDiffView(
            base_content=content.base_content,
            changed_content=content.changed_content,
            path_hint=content.repository_relative_path,
            classes="git-diff-view",
        )

    def compose(self) -> ComposeResult:
        """Mount the literal summary and reusable core view when Textual opens this screen."""
        additions, removals = self._summary_counts(content=self._content)
        with Vertical():
            yield LiteralTextStatic(
                self._build_summary_text(content=self._content, additions=additions, removals=removals),
                classes="git-diff-summary",
            )
            yield LiteralTextStatic(
                "Unified diff · + added · - removed · s side-by-side · w wrap · a gutters · Esc close",
                classes="git-diff-controls",
            )
            with VerticalScroll(id="git-diff-scroll"):
                yield self._view

    @staticmethod
    def _summary_counts(*, content: GitDiffContentDAO) -> tuple[int, int]:
        """Compute summary counts from the same pure model consumed by the core view."""
        model = SloDiffModel.build(base_content=content.base_content, changed_content=content.changed_content)
        return model.addition_count, model.removal_count

    @staticmethod
    def _build_summary_text(*, content: GitDiffContentDAO, additions: int, removals: int) -> str:
        """Format a markup-safe one-line state and line-count summary for the operator."""
        return f"{content.repository_relative_path} — {content.file_state.value} — +{additions} -{removals}"

    async def action_dismiss(self, result: None = None) -> None:
        """Dismiss the focused screen when the operator presses Escape.

        Args:
            result (None, optional): Required Screen action result. Defaults to None.
        """
        await self.dismiss(result)

    def action_toggle_split(self) -> None:
        """Toggle split versus unified composition when the operator presses s."""
        self._view.split = not self._view.split

    def action_toggle_wrap(self) -> None:
        """Toggle soft wrapping when the operator presses w."""
        self._view.wrap = not self._view.wrap

    def action_toggle_annotations(self) -> None:
        """Toggle accessible line-role prefixes when the operator presses a."""
        self._view.annotations = not self._view.annotations
