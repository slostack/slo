"""Unit tests for ``ThinkingSpinner`` (sub-spec 02.a.3).

The spinner is a tiny Textual ``Static`` widget that cycles through
six verbs once mounted. Tests drive ``_rotate_verb`` manually rather
than waiting on Textual's interval timer so they run synchronously.
"""
from __future__ import annotations

from typing import List
from unittest.mock import patch

from src.tui.thinking_spinner import ThinkingSpinner, _VERBS


class TestThinkingSpinner:
    """Cover the constructor seed verb and the rotation behaviour."""

    def test_initial_render_shows_first_verb(self) -> None:
        """Right after construction the spinner shows ``"✦ Pondering…"``."""
        with patch.object(ThinkingSpinner, "update") as mock_update:
            ThinkingSpinner()

            mock_update.assert_called_once_with("✦ Pondering…")

    def test_rotate_verb_cycles_through_verbs(self) -> None:
        """Driving ``_rotate_verb`` advances through every verb and wraps."""
        recorded: List[str] = []

        def _capture(content: str) -> None:
            recorded.append(content)

        with patch.object(ThinkingSpinner, "update", side_effect=_capture):
            spinner: ThinkingSpinner = ThinkingSpinner()
            for _ in range(len(_VERBS) + 1):
                spinner._rotate_verb()

        expected_verbs: List[str] = [
            "Pondering",
            "Investigating",
            "Crafting",
            "Reading",
            "Working",
            "Thinking",
            "Pondering",
            "Investigating",
        ]
        expected_renders: List[str] = [f"✦ {verb}…" for verb in expected_verbs]
        assert recorded == expected_renders

    def test_interval_seconds_is_captured(self) -> None:
        """A custom ``interval_seconds`` is stored on the instance."""
        with patch.object(ThinkingSpinner, "update"):
            spinner: ThinkingSpinner = ThinkingSpinner(interval_seconds=0.25)

            assert spinner._interval_seconds == 0.25

    def test_on_mount_schedules_interval(self) -> None:
        """``on_mount`` calls ``self.set_interval`` with the captured interval."""
        with patch.object(ThinkingSpinner, "update"), patch.object(
            ThinkingSpinner, "set_interval"
        ) as mock_set_interval:
            spinner: ThinkingSpinner = ThinkingSpinner(interval_seconds=0.5)
            spinner.on_mount()

            mock_set_interval.assert_called_once_with(
                interval=0.5,
                callback=spinner._rotate_verb,
            )
