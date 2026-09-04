"""Unit tests for ``ThinkingSpinner`` (sub-spec 02.a.3, restyled in 72.a.5).

The spinner is a small ``Horizontal`` with two child ``Static`` surfaces:
an accent braille activity glyph that rotates every 0.08 seconds, and a
muted status text that rotates through six verbs every ``interval_seconds``
(or carries an override status). Tests drive ``_rotate_braille`` and
``_rotate_verb`` manually rather than waiting on Textual's interval timers
so they run synchronously.
"""

from __future__ import annotations

from unittest.mock import patch

from src.tui.thinking_spinner import (
    _BRAILLE_FRAMES,
    _BRAILLE_INTERVAL_SECONDS,
    _VERBS,
    ThinkingSpinner,
)


class TestThinkingSpinnerConstruction:
    """The constructor seeds both child surfaces with their first frames."""

    def test_initial_glyph_is_first_braille_frame(self) -> None:
        """Right after construction the glyph shows the first ``⠋`` frame."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        assert str(spinner._glyph.content) == _BRAILLE_FRAMES[0]

    def test_initial_text_is_first_verb(self) -> None:
        """Right after construction the text shows ``"Pondering…"``."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        assert str(spinner._text.content) == "Pondering…"

    def test_children_carry_glyph_and_text_classes(self) -> None:
        """CSS can color the glyph and text surfaces independently."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        assert "thinking-spinner-glyph" in spinner._glyph.classes
        assert "thinking-spinner-text" in spinner._text.classes

    def test_composed_children_are_glyph_then_text(self) -> None:
        """The widget composes exactly the glyph followed by the text surface."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        children = list(spinner.compose())

        assert children == [spinner._glyph, spinner._text]

    def test_interval_seconds_is_captured(self) -> None:
        """A custom ``interval_seconds`` is stored on the instance."""
        spinner: ThinkingSpinner = ThinkingSpinner(interval_seconds=0.25)

        assert spinner._interval_seconds == 0.25


class TestThinkingSpinnerBrailleRotation:
    """The fast braille glyph rotates independently of the status text."""

    def test_rotate_braille_advances_through_frames_and_wraps(self) -> None:
        """Driving ``_rotate_braille`` visits every frame, then wraps to the first."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        for expected_frame in _BRAILLE_FRAMES[1:]:
            spinner._rotate_braille()
            assert str(spinner._glyph.content) == expected_frame

        spinner._rotate_braille()
        assert str(spinner._glyph.content) == _BRAILLE_FRAMES[0]

    def test_rotate_braille_does_not_touch_status_text(self) -> None:
        """A glyph rotation leaves the verb surface unchanged."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        spinner._rotate_braille()

        assert str(spinner._text.content) == "Pondering…"


class TestThinkingSpinnerVerbRotation:
    """The slow verb rotation touches only the text surface."""

    def test_rotate_verb_cycles_through_verbs_and_wraps(self) -> None:
        """Driving ``_rotate_verb`` advances through every verb and wraps."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        expected_verbs: list[str] = [*_VERBS[1:], _VERBS[0]]
        for expected_verb in expected_verbs:
            spinner._rotate_verb()
            assert str(spinner._text.content) == f"{expected_verb}…"

    def test_rotate_verb_does_not_touch_braille_glyph(self) -> None:
        """A verb rotation leaves the activity glyph unchanged."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        spinner._rotate_verb()

        assert str(spinner._glyph.content) == _BRAILLE_FRAMES[0]


class TestThinkingSpinnerOverrideStatus:
    """Override status replaces wording without stopping glyph activity."""

    def test_override_text_replaces_verb_text(self) -> None:
        """``set_override_status`` shows the explicit runtime status copy."""
        spinner: ThinkingSpinner = ThinkingSpinner()

        spinner.set_override_status(text="Rate limited; retrying in 1s.")

        assert str(spinner._text.content) == "Rate limited; retrying in 1s."

    def test_override_text_survives_glyph_rotation(self) -> None:
        """The braille glyph keeps rotating while the override copy stays visible."""
        spinner: ThinkingSpinner = ThinkingSpinner()
        spinner.set_override_status(text="Compacting context…")

        spinner._rotate_braille()

        assert str(spinner._glyph.content) == _BRAILLE_FRAMES[1]
        assert str(spinner._text.content) == "Compacting context…"

    def test_verb_rotation_keeps_override_text_visible(self) -> None:
        """A slow verb tick does not displace an active override status."""
        spinner: ThinkingSpinner = ThinkingSpinner()
        spinner.set_override_status(text="Compacting context…")

        spinner._rotate_verb()

        assert str(spinner._text.content) == "Compacting context…"

    def test_clearing_override_restores_current_verb(self) -> None:
        """``set_override_status(text=None)`` resumes the verb rotation display."""
        spinner: ThinkingSpinner = ThinkingSpinner()
        spinner.set_override_status(text="Compacting context…")

        spinner.set_override_status(text=None)

        assert str(spinner._text.content) == "Pondering…"


class TestThinkingSpinnerTimers:
    """Mount schedules the fast glyph and slow verb timers separately."""

    def test_on_mount_schedules_braille_and_verb_intervals(self) -> None:
        """``on_mount`` schedules the 0.08 s glyph timer and the configured verb timer."""
        with patch.object(ThinkingSpinner, "set_interval") as mock_set_interval:
            spinner: ThinkingSpinner = ThinkingSpinner(interval_seconds=0.5)
            spinner.on_mount()

        assert mock_set_interval.call_count == 2
        mock_set_interval.assert_any_call(
            interval=_BRAILLE_INTERVAL_SECONDS,
            callback=spinner._rotate_braille,
        )
        mock_set_interval.assert_any_call(
            interval=0.5,
            callback=spinner._rotate_verb,
        )
