"""Slo's Textual themes and semantic presentation tokens.

``slo-dark`` (near-black/green, the install default) and ``slo-default``
(Tokyo Night hues only for meaning and a quiet foreground ramp for structure)
are both registered. ``slo-default`` is the quieter alternative selected with
``/theme``. Semantic variables are shared by Textual CSS and
Rich content: ``user-msg-bg`` is the user band; tool state background variables
stay neutral; ``thinking-text``, ``md-heading``, and ``border-muted`` style
reasoning, Markdown headings, and stronger separators. ``rule`` / ``border-hairline``,
``text-dim``, ``text-muted``, ``bar-track``, and ``tool-output-bg`` and ``status-error`` are the
hairline, dim/muted text, progress track, expanded tool-output surface, and
exact error-glyph color for component CSS. ``prompt-border*`` colour the prompt
rules; ``list-selection-*`` paint the selected workflow row (focused/blurred
background, left marker, readable text); ``shortcut-key`` colours footer keys.
"""

from __future__ import annotations

from textual.theme import Theme

__all__ = ["SLO_DARK_THEME", "SLO_DEFAULT_THEME"]

SLO_DEFAULT_THEME: Theme = Theme(
    name="slo-default",
    primary="#7aa2f7",
    secondary="#7dcfff",
    warning="#e0af68",
    error="#f7768e",
    success="#9ece6a",
    accent="#7aa2f7",
    foreground="#c0caf5",
    background="#1a1b26",
    surface="#1a1b26",
    panel="#1f2335",
    dark=True,
    luminosity_spread=0.08,
    text_alpha=0.95,
    variables={
        "button-color-foreground": "#1a1b26",
        "screen-selection-background": "#7aa2f7",
        "screen-selection-foreground": "#1a1b26",
        "user-msg-bg": "#1f2335",
        "tool-pending-bg": "#1a1b26",
        "tool-success-bg": "#1a1b26",
        "tool-error-bg": "#1a1b26",
        "thinking-text": "#8089b5",
        "md-heading": "#e0af68",
        "border-muted": "#565f89",
        "rule": "#2a2f45",
        "border-hairline": "#2a2f45",
        "text-dim": "#8089b5",
        "text-muted": "#a9b1d6",
        "bar-track": "#24283b",
        "tool-output-bg": "#16161e",
        "status-error": "#f7768e",
        "prompt-border": "#2a2f45",
        "prompt-border-focus": "#7aa2f7",
        "list-selection-bg": "#283457",
        "list-selection-blurred-bg": "#1f2335",
        "list-selection-marker": "#7aa2f7",
        "list-selection-text": "#c0caf5",
        "shortcut-key": "#7aa2f7",
        "markdown-heading": "bold #e0af68",
        "markdown-muted": "dim #9aa5ce",
        "markdown-quote": "italic #9aa5ce",
        "markdown-emphasis": "italic",
        "markdown-strong": "bold",
        "markdown-inline-code": "#7dcfff",
        "markdown-code": "#c0caf5",
        "markdown-link": "underline #7aa2f7",
        "markdown-code-keyword": "bold #bb9af7",
        "markdown-code-string": "#9ece6a",
        "markdown-code-comment": "italic dim #9aa5ce",
        "markdown-code-number": "#e0af68",
        "markdown-code-name": "#7dcfff",
        "markdown-code-punctuation": "#9aa5ce",
        "markdown-code-diff-added": "#9ece6a",
        "markdown-code-diff-removed": "#f7768e",
        "markdown-code-diff-hunk": "bold #e0af68",
        "markdown-code-diff-file": "bold #7dcfff",
        "auth-surface": "#1f2335",
        "auth-border": "#2a2f45",
        "auth-heading": "#9aa5ce",
        "auth-code": "#e0af68",
        "auth-action-background": "#7aa2f7",
        "auth-action-foreground": "#1a1b26",
        "auth-selection-background": "#414868",
        "auth-selection-foreground": "#c0caf5",
    },
)


SLO_DARK_THEME: Theme = Theme(
    name="slo-dark",
    primary="#00ff7f",
    secondary="#7ec8e3",
    warning="#f0a020",
    error="#ff5555",
    success="#00ff7f",
    accent="#00ff7f",
    foreground="#d8d8d8",
    background="#080808",
    surface="#111111",
    panel="#181818",
    dark=True,
    luminosity_spread=0.08,
    text_alpha=0.92,
    variables={
        # Buttons with accent background need black text to stay readable.
        "button-color-foreground": "#080808",
        # Text selection: bright band + black text (same readability precedent).
        "screen-selection-background": "#00ff7f",
        "screen-selection-foreground": "#080808",
        # Canonical Pi-derived semantic roles (spec 72.a.5).
        "user-msg-bg": "#20252a",
        "tool-pending-bg": "#151b17",
        "tool-success-bg": "#102619",
        "tool-error-bg": "#2d1616",
        "thinking-text": "#8b8b8b",
        "md-heading": "#f0c674",
        "border-muted": "#505050",
        "rule": "#262626",
        "border-hairline": "#262626",
        "text-dim": "#8b8b8b",
        "text-muted": "#b0b0b0",
        "bar-track": "#1e1e1e",
        "tool-output-bg": "#0c0c0c",
        "status-error": "#ff5555",
        # Prompt input rules match the user-message "You" label ($secondary).
        "prompt-border": "#7ec8e3",
        "prompt-border-focus": "#7ec8e3",
        # Selected list rows and footer shortcut keys share the same blue family.
        "list-selection-bg": "#1a2b33",
        "list-selection-blurred-bg": "#20252a",
        "list-selection-marker": "#7ec8e3",
        "list-selection-text": "#f0f0f0",
        "shortcut-key": "#7ec8e3",
        "markdown-heading": "bold #f0c674",
        "markdown-muted": "dim #8b8b8b",
        "markdown-quote": "italic #8b8b8b",
        "markdown-emphasis": "italic",
        "markdown-strong": "bold",
        "markdown-inline-code": "#7ec8e3",
        "markdown-code": "#d8d8d8",
        "markdown-link": "underline #00ff7f",
        "markdown-code-keyword": "bold #d0b57a",
        "markdown-code-string": "#9fd39f",
        "markdown-code-comment": "italic dim #8b8b8b",
        "markdown-code-number": "#f0a020",
        "markdown-code-name": "#7ec8e3",
        "markdown-code-punctuation": "#8b8b8b",
        "markdown-code-diff-added": "#9fd39f",
        "markdown-code-diff-removed": "#ff5555",
        "markdown-code-diff-hunk": "bold #f0a020",
        "markdown-code-diff-file": "bold #7ec8e3",
        # Authentication modal semantic roles (spec 78.a.3).
        "auth-surface": "#151817",
        "auth-border": "#3e5148",
        "auth-heading": "#b8c7bd",
        "auth-code": "#d0b57a",
        "auth-action-background": "#b8c7bd",
        "auth-action-foreground": "#151817",
        "auth-selection-background": "#3e5148",
        "auth-selection-foreground": "#d8d8d8",
    },
)
