"""Behavior and token tests for Slo's sole Textual theme."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from rich.color import Color
from textual.app import App
from textual.selection import SELECT_ALL
from textual.style import Style as TextualStyle
from textual.widgets import Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.auth.credential_dao import ProviderName
from src.auth.oauth_flow import AuthorizationPresentationDAO
from src.auth.oauth_provider import OAuthLoginMethod
from src.tui.authentication.auth_screen import AuthenticationScreen
from src.tui.authentication.widgets.oauth_status import OAuthStatusWidget
from src.tui.theme import SLO_DARK_THEME, SLO_DEFAULT_THEME

_AUTH_TOKENS: dict[str, str] = {
    "auth-surface": "#1f2335",
    "auth-border": "#2a2f45",
    "auth-heading": "#9aa5ce",
    "auth-code": "#e0af68",
    "auth-action-background": "#7aa2f7",
    "auth-action-foreground": "#1a1b26",
    "auth-selection-background": "#414868",
    "auth-selection-foreground": "#c0caf5",
}

_CANONICAL_PI_TOKENS: tuple[str, ...] = (
    "user-msg-bg",
    "tool-pending-bg",
    "tool-success-bg",
    "tool-error-bg",
    "thinking-text",
    "md-heading",
    "border-muted",
)

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


class TestSloDefaultThemeTokens:
    """Verify the only Slo theme uses the new restrained palette."""

    def test_name_and_core_surface(self) -> None:
        assert SLO_DEFAULT_THEME.name == "slo-default"
        assert SLO_DEFAULT_THEME.background == "#1a1b26"
        assert SLO_DEFAULT_THEME.surface == "#1a1b26"
        assert SLO_DEFAULT_THEME.panel == "#1f2335"

    def test_semantic_colors_are_preserved(self) -> None:
        assert SLO_DEFAULT_THEME.accent == "#7aa2f7"
        assert SLO_DEFAULT_THEME.secondary == "#7dcfff"
        assert SLO_DEFAULT_THEME.success == "#9ece6a"
        assert SLO_DEFAULT_THEME.warning == "#e0af68"
        assert SLO_DEFAULT_THEME.error == "#f7768e"
        assert SLO_DEFAULT_THEME.foreground == "#c0caf5"

    def test_user_band_tool_surfaces_and_structure_tokens_are_quiet(self) -> None:
        variables: dict[str, str] = SLO_DEFAULT_THEME.variables
        assert variables["user-msg-bg"] == "#1f2335"
        assert variables["tool-pending-bg"] == "#1a1b26"
        assert variables["tool-success-bg"] == "#1a1b26"
        assert variables["tool-error-bg"] == "#1a1b26"
        assert variables["border-hairline"] == variables["rule"] == "#2a2f45"
        assert variables["text-dim"] == "#8089b5"
        assert variables["text-muted"] == "#a9b1d6"
        assert variables["bar-track"] == "#24283b"
        assert variables["tool-output-bg"] == "#16161e"

    def test_theme_registry_contains_slo_dark_default_and_slo_default(self) -> None:
        from src.tui.app import SloTUI

        app: SloTUI = SloTUI(session=_build_theme_test_session())
        assert app.DEFAULT_THEME == "slo-dark"
        assert {name for name in app.available_themes if name.startswith("slo-")} == {
            "slo-dark",
            "slo-default",
        }

    def test_button_and_selection_tokens_are_readable(self) -> None:
        assert SLO_DEFAULT_THEME.variables["button-color-foreground"] == "#1a1b26"
        assert SLO_DEFAULT_THEME.variables["screen-selection-background"] == "#7aa2f7"
        assert SLO_DEFAULT_THEME.variables["screen-selection-foreground"] == "#1a1b26"

    def test_theme_variables_cover_every_semantic_and_presentation_role(self) -> None:
        assert set(SLO_DEFAULT_THEME.variables) == {
            "button-color-foreground",
            "screen-selection-background",
            "screen-selection-foreground",
            *_CANONICAL_PI_TOKENS,
            *_MARKDOWN_COMPILER_TOKENS,
            *_AUTH_TOKENS,
            "rule",
            "border-hairline",
            "text-dim",
            "text-muted",
            "bar-track",
            "tool-output-bg",
            "status-error",
            "prompt-border",
            "prompt-border-focus",
            "list-selection-bg",
            "list-selection-blurred-bg",
            "list-selection-marker",
            "list-selection-text",
            "shortcut-key",
        }

    def test_both_themes_define_the_same_variables(self) -> None:
        """Every token one Slo theme defines exists in the other, so CSS never breaks on a switch."""
        assert set(SLO_DARK_THEME.variables) == set(SLO_DEFAULT_THEME.variables)

    def test_slo_dark_selection_and_shortcuts_use_the_user_label_blue(self) -> None:
        """slo-dark's selection marker and footer keys match the "You"/prompt colour."""
        assert SLO_DARK_THEME.variables["list-selection-marker"] == SLO_DARK_THEME.secondary
        assert SLO_DARK_THEME.variables["shortcut-key"] == SLO_DARK_THEME.secondary

    def test_slo_dark_prompt_borders_match_user_label_color(self) -> None:
        """slo-dark paints PromptInput rules in the user-message "You" colour ($secondary)."""
        assert SLO_DARK_THEME.variables["prompt-border"] == SLO_DARK_THEME.secondary
        assert SLO_DARK_THEME.variables["prompt-border-focus"] == SLO_DARK_THEME.secondary

    def test_authentication_text_pairs_meet_wcag_aa_contrast(self) -> None:
        pairs: tuple[tuple[str, str], ...] = (
            ("auth-heading", "auth-surface"),
            ("auth-code", "auth-surface"),
            ("auth-action-foreground", "auth-action-background"),
            ("auth-selection-foreground", "auth-selection-background"),
        )
        for foreground, background in pairs:
            assert (
                _contrast_ratio(
                    foreground=SLO_DEFAULT_THEME.variables[foreground],
                    background=SLO_DEFAULT_THEME.variables[background],
                )
                >= 4.5
            )


class _AuthenticationSelectionHarness(App):
    """Mount the auth modal using the sole registered Slo theme."""

    def __init__(self) -> None:
        """Register the theme before Textual parses the auth screen stylesheet."""
        super().__init__()
        self.register_theme(SLO_DEFAULT_THEME)
        self.theme = SLO_DEFAULT_THEME.name

    def on_mount(self) -> None:
        """Push the authentication screen before computed selection inspection."""
        self.push_screen(AuthenticationScreen())


class TestAuthSelectionOverlay:
    """Pilot-check the actual authentication selection overlay color."""

    @pytest.mark.asyncio
    async def test_selection_overlay_uses_auth_tokens(self) -> None:
        app: _AuthenticationSelectionHarness = _AuthenticationSelectionHarness()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
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

        assert background is not None and foreground is not None
        assert background.get_truecolor().hex == _AUTH_TOKENS["auth-selection-background"]
        assert foreground.get_truecolor().hex == _AUTH_TOKENS["auth-selection-foreground"]


def _build_theme_test_session() -> SloAgentSession:
    """Build an inert real session for registered-theme inspection."""
    return SloAgentSession(
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="unused")])),
        workdir=Path("."),
        session_id=str(uuid4()),
    )
