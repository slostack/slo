"""Tests for ``TaskPreview`` (feature 94 a.2, exact projection rules).

The 150-code-point cap applies after control stripping and whitespace
normalization, so every boundary below is measured on the normalized text.
"""

from __future__ import annotations

import pytest

from src.agents.slo_agent.orchestrator.task_preview import TaskPreview

_CAP: int = 150


class TestPreviewBoundaries:
    """Normalized lengths 0/149/150/151 and the ellipsis rule."""

    @pytest.mark.parametrize(
        ("task_text", "expected"),
        [
            ("", ""),
            ("a" * 149, "a" * 149),
            ("a" * 150, "a" * 150),
            ("a" * 151, "a" * 149 + "…"),
        ],
        ids=["normalized-0", "normalized-149", "normalized-150", "normalized-151"],
    )
    def test_preview_boundaries(self, task_text: str, expected: str) -> None:
        """Text up to the cap is unchanged; longer text keeps 149 code points plus an ellipsis."""
        preview: str = TaskPreview.build(task_text=task_text)

        assert preview == expected
        assert len(preview) <= _CAP

    def test_cap_counts_unicode_code_points_not_bytes_or_cells(self) -> None:
        """Wide and multi-byte characters each count as one code point, ellipsis included."""
        preview: str = TaskPreview.build(task_text="界" * 151)

        assert preview == "界" * 149 + "…"
        assert len(preview) == _CAP

    def test_whitespace_only_text_normalizes_to_empty(self) -> None:
        """Whitespace alone never produces a visible label."""
        assert TaskPreview.build(task_text=" \t\n\r  ") == ""


class TestNormalization:
    """Control stripping and whitespace collapsing precede the length measurement."""

    def test_normalization_shrinks_below_cap(self) -> None:
        """200 raw code points normalize to 99, so no ellipsis is added (R2 MINOR-1)."""
        raw: str = "a   " * 50

        preview: str = TaskPreview.build(task_text=raw)

        assert len(raw) == 200
        assert preview == " ".join(["a"] * 50)
        assert len(preview) == 99
        assert not preview.endswith("…")

    def test_newlines_and_tabs_collapse_to_single_spaces(self) -> None:
        """Multi-line tasks become one literal row."""
        assert TaskPreview.build(task_text="  fix\n\nthe\tbug \r\n now ") == "fix the bug now"

    @pytest.mark.parametrize(
        ("task_text", "expected"),
        [
            ("red\x1b[31mtext", "red[31mtext"),
            ("bell\x07here", "bellhere"),
            ("nul\x00byte", "nulbyte"),
            ("del\x7fchar", "delchar"),
            ("c1\x9bcsi", "c1csi"),
            ("osc\x1b]8;;http://x\x07link", "osc]8;;http://xlink"),
        ],
        ids=["esc", "bel", "nul", "del", "c1-csi", "osc-hyperlink"],
    )
    def test_c0_and_c1_controls_are_stripped(self, task_text: str, expected: str) -> None:
        """No C0/C1 control or DEL survives, so no terminal sequence can execute."""
        preview: str = TaskPreview.build(task_text=task_text)

        assert preview == expected
        assert not any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in preview)

    def test_control_stripping_precedes_length_measurement(self) -> None:
        """150 visible characters padded with controls are not truncated."""
        raw: str = "\x1b".join("a" * 150)

        preview: str = TaskPreview.build(task_text=raw)

        assert preview == "a" * 150

    def test_markup_brackets_are_retained_literally(self) -> None:
        """Rich/Textual markup is data here; the formatter neither escapes nor removes it."""
        assert TaskPreview.build(task_text="[bold]x[/bold] [link=y]z") == "[bold]x[/bold] [link=y]z"

    def test_non_ascii_text_is_preserved(self) -> None:
        """Ordinary Unicode letters and emoji are kept as-is."""
        assert TaskPreview.build(task_text="Résumé 修正 🚀") == "Résumé 修正 🚀"
