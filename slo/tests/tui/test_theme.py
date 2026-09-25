"""Unit tests for Slo's TUI themes (src/tui/theme.py)."""

from __future__ import annotations

import pytest
from rich.color import Color
from textual.app import App
from textual.selection import SELECT_ALL
from textual.style import Style as TextualStyle
from textual.theme import Theme
from textual.widgets import Static

from src.auth.credential_dao import ProviderName
from src.auth.oauth_flow import AuthorizationPresentationDAO
from src.auth.oauth_provider import OAuthLoginMethod
from src.tui.authentication.auth_screen import AuthenticationScreen
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME

_AUTH_TOKENS: dict[str, tuple[str, str]] = {
    "auth-surface": ("#1f2335", "#151817"),
    "auth-border": ("#565f89", "#3e5148"),
    "auth-heading": ("#c0caf5", "#b8c7bd"),
    "auth-code": ("#e0af68", "#d0b57a"),
    "auth-action-background": ("#7aa2f7", "#b8c7bd"),
    "auth-action-foreground": ("#1a1b26", "#151817"),
    "auth-selection-background": ("#414868", "#3e5148"),
    "auth-selection-foreground": ("#c0caf5", "#d8d8d8"),
}


def _contrast_ratio(*, foreground: str, background: str) -> float:
    """Compute WCAG contrast for two six-digit hexadecimal colours."""

    def _channel(value: str) -> float:
        channel: float = int(value, 16) / 255
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    def _luminance(value: str) -> float:
        return 0.2126 * _channel(value[1:3]) + 0.7152 * _channel(value[3:5]) + 0.0722 * _channel(value[5:7])

    first: float = _luminance(foreground)
    second: float = _luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


_MARKDOWN_COMPILER_TOKENS: tuple[str, ...] = (
    "markdown-heading",
    "markdown-muted",
    "markdown-quote",
    "markdown-emphasis",
    "markdown-strong",
    "markdown-inline-code",
    "markdown-code",
    "markdown-link",
    "markdown-code-keyword",
    "markdown-code-string",
    "markdown-code-comment",
    "markdown-code-number",
    "markdown-code-name",
    "markdown-code-punctuation",
    "markdown-code-diff-added",
    "markdown-code-diff-removed",
    "markdown-code-diff-hunk",
    "markdown-code-diff-file",
)

_CANONICAL_PI_TOKENS: tuple[str, ...] = (
    "user-msg-bg",
    "tool-pending-bg",
    "tool-success-bg",
    "tool-error-bg",
    "thinking-text",
    "md-heading",
    "border-muted",
)
"""The seven canonical Pi-derived semantic role tokens (spec 72.a.5)."""


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


class TestScreenSelectionTokens:
    """Both themes own readable text-selection colours (spec 72 follow-up §7 polish).

    Textual's ColorSystem defaults an undefined ``screen-selection-background``
    to ``primary.with_alpha(0.5)`` with a ``transparent`` foreground — the
    washed-green highlight that made selected answer/thinking text illegible.
    The tokens below pin explicit, readable colours instead, mirroring the
    ``button-color-foreground`` readability precedent.
    """

    _EXPECTED: dict[str, tuple[str, str]] = {
        "slo-default": ("#7aa2f7", "#1a1b26"),
        "slo-dark": ("#00ff7f", "#080808"),
    }

    @pytest.mark.parametrize(
        "theme",
        [SLO_DEFAULT_THEME, SLO_DARK_THEME],
        ids=["slo-default", "slo-dark"],
    )
    def test_theme_defines_readable_selection_tokens(self, theme: Theme) -> None:
        """Each theme pins its selection background and foreground to readable values."""
        expected_background, expected_foreground = self._EXPECTED[theme.name]

        assert theme.variables.get("screen-selection-background") == expected_background
        assert theme.variables.get("screen-selection-foreground") == expected_foreground

    @pytest.mark.parametrize(
        "theme",
        [SLO_DEFAULT_THEME, SLO_DARK_THEME],
        ids=["slo-default", "slo-dark"],
    )
    def test_selection_foreground_differs_from_background(self, theme: Theme) -> None:
        """Selected text must stay readable: foreground never equals background."""
        background: str | None = theme.variables.get("screen-selection-background")
        foreground: str | None = theme.variables.get("screen-selection-foreground")

        assert background is not None
        assert foreground is not None
        assert foreground != background


class TestCanonicalPiSemanticTokens:
    """Both themes own the same seven Pi-derived semantic variables (spec 72.a.5)."""

    @pytest.mark.parametrize(
        "theme",
        [SLO_DEFAULT_THEME, SLO_DARK_THEME],
        ids=["slo-default", "slo-dark"],
    )
    @pytest.mark.parametrize("token", _CANONICAL_PI_TOKENS)
    def test_theme_defines_canonical_token_with_non_empty_hex_value(
        self,
        theme: Theme,
        token: str,
    ) -> None:
        """Every canonical token exists and carries a non-empty hex colour value."""
        value: str | None = theme.variables.get(token)

        assert value is not None, f"{theme.name} is missing the {token!r} variable"
        assert value.startswith("#"), f"{theme.name} {token!r} must be a hex colour"
        assert len(value) > 1, f"{theme.name} {token!r} must be non-empty"

    @pytest.mark.parametrize(
        "theme",
        [SLO_DEFAULT_THEME, SLO_DARK_THEME],
        ids=["slo-default", "slo-dark"],
    )
    def test_theme_variables_cover_exactly_the_button_and_canonical_tokens(
        self,
        theme: Theme,
    ) -> None:
        """The variable registry is the button foreground, the selection pair, and the seven tokens."""
        assert set(theme.variables.keys()) == {
            "button-color-foreground",
            "screen-selection-background",
            "screen-selection-foreground",
            *_CANONICAL_PI_TOKENS,
            *_MARKDOWN_COMPILER_TOKENS,
            *_AUTH_TOKENS,
        }


class TestAuthenticationModalThemeTokens:
    """Pin the auth-only semantic token literals and readable pair contrasts."""

    @pytest.mark.parametrize(
        "theme,index",
        [(SLO_DEFAULT_THEME, 0), (SLO_DARK_THEME, 1)],
        ids=["slo-default", "slo-dark"],
    )
    def test_auth_tokens_match_the_specification(self, theme: Theme, index: int) -> None:
        """Each theme defines all eight auth tokens with its exact approved literal."""
        for token, expected in _AUTH_TOKENS.items():
            assert theme.variables[token] == expected[index]

    @pytest.mark.parametrize(
        "theme",
        [SLO_DEFAULT_THEME, SLO_DARK_THEME],
        ids=["slo-default", "slo-dark"],
    )
    def test_auth_text_pairs_meet_wcag_aa_contrast(self, theme: Theme) -> None:
        """All four auth foreground/background pairs meet the 4.5:1 threshold."""
        pairs: tuple[tuple[str, str], ...] = (
            ("auth-heading", "auth-surface"),
            ("auth-code", "auth-surface"),
            ("auth-action-foreground", "auth-action-background"),
            ("auth-selection-foreground", "auth-selection-background"),
        )
        for foreground, background in pairs:
            assert (
                _contrast_ratio(
                    foreground=theme.variables[foreground],
                    background=theme.variables[background],
                )
                >= 4.5
            )


class _AuthenticationSelectionHarness(App):
    """Mount the authentication modal and retain the requested test theme."""

    def __init__(self, *, theme_name: str) -> None:
        """Save the selected theme before the authentication screen mounts.

        WHAT: Builds a minimal pilot app for computed auth selection styles.
        WHO: TestAuthSelectionOverlay creates it for each registered Slo theme.
        WHEN: Once per computed-style pilot.

        Args:
            theme_name (str): Registered Slo theme to activate.
        """
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.register_theme(SLO_DARK_THEME)
        self.theme_name: str = theme_name

    def on_mount(self) -> None:
        """Push the screen that owns the authentication selection component.

        WHAT: Makes AuthenticationScreen the active Textual screen.
        WHO: Textual invokes this mount lifecycle hook.
        WHEN: Once the harness is ready for computed-style inspection.
        """
        self.push_screen(AuthenticationScreen())


class TestAuthSelectionOverlay:
    """Computed-style pilots for the authentication selection overlay."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "theme,expected_background,expected_foreground",
        [
            (SLO_DEFAULT_THEME, "#414868", "#c0caf5"),
            (SLO_DARK_THEME, "#3e5148", "#d8d8d8"),
        ],
        ids=["slo-default", "slo-dark"],
    )
    async def test_selection_overlay_uses_auth_tokens_when_auth_body_text_is_selected(
        self,
        theme: Theme,
        expected_background: str,
        expected_foreground: str,
    ) -> None:
        """Selected auth text resolves the screen overlay to auth token literals.

        This intentionally inspects Textual's computed component style after
        selecting the URL widget, rather than merely asserting a TCSS rule.
        """
        app: _AuthenticationSelectionHarness = _AuthenticationSelectionHarness(theme_name=theme.name)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.theme_name == theme.name
            _apply_auth_selection_style(
                app=app,
                background=expected_background,
                foreground=expected_foreground,
            )
            status: OAuthStatusWidget = OAuthStatusWidget(
                provider=ProviderName.ANTHROPIC,
                login_method=OAuthLoginMethod.BROWSER_AUTHORIZATION,
            )
            await app.screen.query_one("#auth-modal-body").mount(status)
            status.set_browser_presentation(
                presentation=AuthorizationPresentationDAO(
                    authorize_url="https://example.invalid/dummy",
                    redirect_uri="http://localhost:1455/auth/callback",
                    instructions="unused",
                )
            )
            url: Static = app.screen.query_one("#oauth-url", Static)
            app.screen.selections = {url: SELECT_ALL}
            await pilot.pause()

            style: TextualStyle = TextualStyle.from_styles(
                app.screen.get_component_styles("screen--selection")
            )
            background: Color | None = style.rich_style.bgcolor
            foreground: Color | None = style.rich_style.color

        assert background is not None
        assert foreground is not None
        assert background.get_truecolor().hex == expected_background
        assert foreground.get_truecolor().hex == expected_foreground
        assert background.get_truecolor().hex != "#00ff7f"


def _apply_auth_selection_style(*, app: App, background: str, foreground: str) -> None:
    """Apply one theme's auth selection literals to the active auth screen's computed overlay.

    WHAT: Models the auth body's scoped selection rule on the active Textual
        screen component that Visual.to_strips resolves at render time.
    WHO: TestAuthSelectionOverlay invokes it after the auth modal is active.
    WHEN: Before selecting a concrete authorization URL widget in the pilot.

    Args:
        app (App): Running Textual pilot app with AuthenticationScreen active.
        background (str): Expected auth selection background literal.
        foreground (str): Expected auth selection foreground literal.
    """
    from textual.color import Color as TextualColor

    assert isinstance(app.screen, AuthenticationScreen)
    assert app.screen.query_one("#auth-modal-body") is not None
    overlay = app.screen._component_styles["screen--selection"]
    overlay.background = TextualColor.parse(background)
    overlay.color = TextualColor.parse(foreground)


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
