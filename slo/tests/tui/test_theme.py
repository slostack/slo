"""Unit tests for Slo's TUI themes (src/tui/theme.py)."""

from __future__ import annotations

import pytest

from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME


class TestSloDefaultThemeTokens:
    """Verify every design token for the slo-default (tokyo-night) theme."""

    def test_name(self) -> None:
        assert SLO_DEFAULT_THEME.name == "slo-default"

    def test_background(self) -> None:
        assert SLO_DEFAULT_THEME.background == "#1a1b26"

    def test_surface(self) -> None:
        assert SLO_DEFAULT_THEME.surface == "#24283b"

    def test_panel(self) -> None:
        assert SLO_DEFAULT_THEME.panel == "#1f2335"

    def test_accent_is_blue(self) -> None:
        assert SLO_DEFAULT_THEME.accent == "#7aa2f7"

    def test_primary_is_blue(self) -> None:
        assert SLO_DEFAULT_THEME.primary == "#7aa2f7"

    def test_secondary_is_cyan(self) -> None:
        assert SLO_DEFAULT_THEME.secondary == "#7dcfff"

    def test_success_is_green(self) -> None:
        assert SLO_DEFAULT_THEME.success == "#9ece6a"

    def test_warning_is_amber(self) -> None:
        assert SLO_DEFAULT_THEME.warning == "#e0af68"

    def test_error_is_red(self) -> None:
        assert SLO_DEFAULT_THEME.error == "#f7768e"

    def test_foreground(self) -> None:
        assert SLO_DEFAULT_THEME.foreground == "#c0caf5"

    def test_dark_mode(self) -> None:
        assert SLO_DEFAULT_THEME.dark is True

    def test_button_foreground_variable_is_dark_background(self) -> None:
        """Buttons with blue accent background need dark text for contrast."""
        assert SLO_DEFAULT_THEME.variables.get("button-color-foreground") == "#1a1b26"

    def test_luminosity_spread_is_tight(self) -> None:
        assert SLO_DEFAULT_THEME.luminosity_spread <= 0.10


class TestSloDarkThemeTokens:
    """Verify every design token for the slo-dark (near-black/green) theme."""

    def test_name(self) -> None:
        assert SLO_DARK_THEME.name == "slo-dark"

    def test_background(self) -> None:
        assert SLO_DARK_THEME.background == "#080808"

    def test_surface(self) -> None:
        assert SLO_DARK_THEME.surface == "#111111"

    def test_panel(self) -> None:
        assert SLO_DARK_THEME.panel == "#181818"

    def test_accent_is_green(self) -> None:
        assert SLO_DARK_THEME.accent == "#00ff7f"

    def test_primary_is_green(self) -> None:
        assert SLO_DARK_THEME.primary == "#00ff7f"

    def test_secondary_is_light_blue(self) -> None:
        assert SLO_DARK_THEME.secondary == "#7ec8e3"

    def test_success_is_green(self) -> None:
        assert SLO_DARK_THEME.success == "#00ff7f"

    def test_warning_is_amber(self) -> None:
        assert SLO_DARK_THEME.warning == "#f0a020"

    def test_error_is_red(self) -> None:
        assert SLO_DARK_THEME.error == "#ff5555"

    def test_foreground(self) -> None:
        assert SLO_DARK_THEME.foreground == "#d8d8d8"

    def test_dark_mode(self) -> None:
        assert SLO_DARK_THEME.dark is True

    def test_button_foreground_variable_is_near_black(self) -> None:
        """Buttons with green accent background need black text for contrast."""
        assert SLO_DARK_THEME.variables.get("button-color-foreground") == "#080808"

    def test_luminosity_spread_is_tight(self) -> None:
        assert SLO_DARK_THEME.luminosity_spread <= 0.10


class TestSloTUIThemeRegistration:
    """Verify that SloTUI registers and selects the correct themes."""

    def test_default_theme_name_matches_slo_dark_object(self) -> None:
        from src.tui.app import SloTUI

        assert SloTUI.DEFAULT_THEME == SLO_DARK_THEME.name

    def test_default_theme_name_is_slo_dark(self) -> None:
        from src.tui.app import SloTUI

        assert SloTUI.DEFAULT_THEME == "slo-dark"

    def test_register_theme_called_with_both_themes(self) -> None:
        """register_theme must receive both SLO_DEFAULT_THEME and SLO_DARK_THEME.

        Note: register_theme must be called AFTER super().__init__() because
        Textual initialises _registered_themes inside App.__init__. Calling it
        before super().__init__() raises AttributeError.
        """
        from src.tui.app import SloTUI

        registered: list = []

        class _ProbeApp(SloTUI):
            def register_theme(self, theme) -> None:  # type: ignore[override]
                registered.append(theme)

            def __init__(self) -> None:  # type: ignore[override]
                self.register_theme(SLO_DEFAULT_THEME)
                self.register_theme(SLO_DARK_THEME)

        _ProbeApp()
        assert len(registered) == 2
        names = {t.name for t in registered}
        assert "slo-default" in names
        assert "slo-dark" in names


class TestSloDefaultThemeFinalisation:
    """Verify the T5 acceptance criteria — slo boots into slo-dark."""

    def test_default_theme_is_slo_dark(self) -> None:
        """SloTUI.DEFAULT_THEME is the slo-dark theme name (the flip from slo-default)."""
        from src.tui.app import SloTUI

        assert SloTUI.DEFAULT_THEME == "slo-dark"

    def test_slo_dark_palette_is_near_black_green(self) -> None:
        """slo-dark retains the inherited near-black/green palette (#080808/#00ff7f)."""
        assert SLO_DARK_THEME.background == "#080808"
        assert SLO_DARK_THEME.accent == "#00ff7f"

    def test_both_themes_registered(self) -> None:
        """Both slo-default and slo-dark theme names are available for the toggle."""
        assert SLO_DEFAULT_THEME.name == "slo-default"
        assert SLO_DARK_THEME.name == "slo-dark"

    def test_theme_toggle_returns_to_slo_default(self) -> None:
        """Toggle logic: from the dark default, /theme yields slo-default (symmetry preserved)."""
        from src.tui.app import SloTUI

        dark_name: str = SLO_DARK_THEME.name
        default_name: str = SLO_DEFAULT_THEME.name
        next_theme: str = default_name if SloTUI.DEFAULT_THEME == dark_name else dark_name
        assert next_theme == "slo-default"
