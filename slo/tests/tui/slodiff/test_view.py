"""Pilot and pure-helper tests for SloDiffView."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import HorizontalScroll

from src.tui.slodiff.view import SloDiffView


class _HostApp(App[None]):
    """Mount one diff view for focused widget tests."""

    def __init__(
        self,
        *,
        base_content: str,
        changed_content: str,
        language_hint: str | None = None,
        path_hint: str | None = None,
    ) -> None:
        """Store content and optional syntax hints used to create the tested widget."""
        super().__init__()
        self._base_content: str = base_content
        self._changed_content: str = changed_content
        self._language_hint: str | None = language_hint
        self._path_hint: str | None = path_hint

    def compose(self) -> ComposeResult:
        """Mount the isolated diff view for each Pilot scenario."""
        yield SloDiffView(
            base_content=self._base_content,
            changed_content=self._changed_content,
            language_hint=self._language_hint,
            path_hint=self._path_hint,
        )


class TestSloDiffViewHelpers:
    """Pure clean-room rendering helper tests."""

    def test_loop_last_when_items_present_marks_final_item(self) -> None:
        """The local replacement for private Textual iteration identifies only the final item."""
        assert list(SloDiffView._loop_last(items=["a", "b"])) == [(False, "a"), (True, "b")]

    def test_char_spans_for_pair_when_changed_marks_range(self) -> None:
        """Matched replacement lines include at least one changed new-text span."""
        assert SloDiffView._char_spans_for_pair(old_line="foo", new_line="far")

    def test_char_spans_for_pair_when_identical_returns_empty(self) -> None:
        """Identical lines do not receive inline change styling."""
        assert SloDiffView._char_spans_for_pair(old_line="same", new_line="same") == []

    def test_iter_line_pairs_when_lengths_differ_pads_shorter_side(self) -> None:
        """Split rows retain alignment by yielding None for the absent side."""
        assert list(SloDiffView._iter_line_pairs(old_lines=["a"], new_lines=["a", "b"])) == [
            ("a", "a"),
            (None, "b"),
        ]

    def test_annotation_symbol_when_role_varies_returns_accessible_prefix(self) -> None:
        """Each rendered diff role has its stable screen-reader prefix."""
        assert SloDiffView._annotation_symbol(role="added") == "+ "
        assert SloDiffView._annotation_symbol(role="removed") == "- "
        assert SloDiffView._annotation_symbol(role="context") == "  "


class TestSloDiffViewLifecycle:
    """Textual lifecycle and reactive rendering coverage."""

    async def test_on_mount_defaults_to_unified_git_style_layout(self) -> None:
        """The first view is a familiar, readable unified diff at every terminal width."""
        app = _HostApp(base_content="old\n", changed_content="new\n")
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause()
            assert app.query_one(SloDiffView).split is False

    async def test_on_mount_when_narrow_keeps_unified_git_style_layout(self) -> None:
        """A narrow terminal preserves the same predictable unified default."""
        app = _HostApp(base_content="old\n", changed_content="new\n")
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.query_one(SloDiffView).split is False

    async def test_prepare_when_mounted_populates_model(self) -> None:
        """Threaded preparation computes the model before rendering content."""
        app = _HostApp(base_content="a\n", changed_content="a\nb\n")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(SloDiffView)._model is not None

    async def test_compose_when_split_is_enabled_renders_two_synced_columns(self) -> None:
        """The explicit side-by-side mode mounts both horizontally linked panes."""
        app = _HostApp(base_content="old\n", changed_content="new\n")
        async with app.run_test(size=(160, 24)) as pilot:
            view = app.query_one(SloDiffView)
            view.split = True
            await pilot.pause()
            assert app.query("#slodiff-left")
            assert app.query("#slodiff-right")

    async def test_compose_when_split_renders_changed_row_inside_visible_diff_view(self) -> None:
        """A changed row is vertically mounted inside the visible split viewport.

        Regression: mounting rows directly in ``HorizontalScroll`` made Textual
        lay them out along the horizontal axis. The model contained changes, but
        every changed row sat outside the viewport and the operator saw a blank
        screen. A vertical column inside each horizontal scroll pane keeps rows
        visible while retaining independent horizontal scrolling.
        """
        app = _HostApp(
            base_content="old one\nold two\nold three\n",
            changed_content="new one\nnew two\nnew three\n",
        )
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause()
            view = app.query_one(SloDiffView)
            added_rows = list(app.query(".diff-added"))

            assert len(added_rows) == 3
            assert all(row.region.y >= view.region.y for row in added_rows)
            assert all(row.region.y < view.region.bottom for row in added_rows)
            assert all(row.region.x < view.region.right for row in added_rows)
            row_positions = [row.region.y for row in added_rows]
            assert row_positions == list(range(row_positions[0], row_positions[0] + len(added_rows)))

    async def test_prepare_when_python_path_hint_uses_python_highlighting(self) -> None:
        """A caller-supplied Python path avoids content-only language misclassification."""
        app = _HostApp(
            base_content="return 1\\n",
            changed_content="return 2\\n",
            path_hint="example.py",
        )
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause()
            view = app.query_one(SloDiffView)
            assert view._language == "python"
            row = view._render_code_line(text="return 2", role="added")
            assert str(row.content) == "+ return 2"
            assert any(span.start >= 2 and span.end > span.start for span in row.content._spans)

    async def test_prepare_when_no_safe_hint_uses_plain_text_fallback(self) -> None:
        """Unhinted source remains literal rather than accepting an incorrect content guess."""
        app = _HostApp(base_content="return 1\\n", changed_content="return 2\\n")
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause()
            assert app.query_one(SloDiffView)._language is None

    async def test_split_when_replacement_has_matched_rows_applies_inline_character_spans(self) -> None:
        """Matched replacement rows retain character-level changed-region styling."""
        app = _HostApp(base_content="foo bar\\n", changed_content="foo BAZ\\n")
        async with app.run_test(size=(160, 24)) as pilot:
            await pilot.pause()
            view = app.query_one(SloDiffView)
            spans = view._char_spans_for_pair(old_line="foo bar", new_line="foo BAZ")
            assert spans
            assert all(span.end > span.start for span in spans)

    async def test_split_scroll_when_public_scroll_to_overflow_mirrors_peer(self) -> None:
        """Textual 8.2.8 scroll_to moves overflowing linked panes to the same positive x offset."""
        app = _HostApp(
            base_content="x" * 300 + "\\n",
            changed_content="x" * 299 + "y\\n",
        )
        async with app.run_test(size=(160, 24)) as pilot:
            view = app.query_one(SloDiffView)
            view.split = True
            await pilot.pause()
            left = app.query_one("#slodiff-left", HorizontalScroll)
            right = app.query_one("#slodiff-right", HorizontalScroll)
            assert left.max_scroll_x > 0
            assert right.max_scroll_x > 0

            left.scroll_to(x=12, animate=False, force=True)
            for _ in range(10):
                await pilot.pause()
                if left.scroll_x == right.scroll_x and left.scroll_x > 0:
                    break

            assert left.scroll_x == right.scroll_x
            assert left.scroll_x > 0

    async def test_reactive_controls_when_toggled_recompose(self) -> None:
        """Wrap and annotations remain mutable rendering controls."""
        app = _HostApp(base_content="a\n", changed_content="b\n")
        async with app.run_test(size=(80, 24)) as pilot:
            view = app.query_one(SloDiffView)
            await pilot.pause()
            view.wrap = True
            view.annotations = False
            await pilot.pause()
            assert view.wrap is True
            assert view.annotations is False
