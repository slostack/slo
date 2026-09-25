"""Slo TUI themes.

Mirrors the design tokens used in the project homepage (finalized.html).

Both themes also define the seven canonical Pi-derived semantic role tokens
(spec 72.a.5) in ``Theme.variables`` — the single role registry consumed by
widget CSS through ``$<token>`` references:

  user-msg-bg       user-only background band
  tool-pending-bg   tool block awaiting terminal state
  tool-success-bg   tool block with a recorded result
  tool-error-bg     tool block explicitly terminal/incomplete
  thinking-text     muted foreground for reasoning segments
  md-heading        warm foreground for assistant markdown headings
  border-muted      low-emphasis turn rule / quiet boundary

Both themes also pin ``screen-selection-background`` /
``screen-selection-foreground`` (bright accent band + dark text) so selected
transcript text stays readable — Textual's alpha-blended default hid the
text on these palettes.

slo-default (tokyo-night palette):
  background  #1a1b26  deep night canvas
  surface     #24283b  lifted surface
  panel       #1f2335  panel/card background
  accent      #7aa2f7  blue — primary accent (links, borders, cursor)
  primary     #7aa2f7  same blue — primary actions
  secondary   #7dcfff  cyan — user message colour
  success     #9ece6a  green — tool-call headline
  warning     #e0af68  amber — rate-limit / abort
  error       #f7768e  red — auth/fatal
  foreground  #c0caf5  body text

slo-dark (near-black/green palette — secondary theme):
  background  #080808  near-black canvas
  surface     #111111  slightly lifted surface
  panel       #181818  panel/card background
  accent      #00ff7f  bright green — primary accent
  primary     #00ff7f  same green — primary actions
  secondary   #7ec8e3  light blue — user message colour
  success     #00ff7f  green — tool-call headline
  warning     #f0a020  amber — rate-limit / abort
  error       #ff5555  red — auth/fatal
  foreground  #d8d8d8  body text
"""

from __future__ import annotations

from textual.theme import Theme

__all__ = ["SLO_DEFAULT_THEME", "SLO_DARK_THEME"]

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
    surface="#24283b",
    panel="#1f2335",
    dark=True,
    luminosity_spread=0.08,
    text_alpha=0.95,
    variables={
        # Buttons with accent background need dark text to stay readable.
        "button-color-foreground": "#1a1b26",
        # Text selection: bright band + dark text (same readability precedent).
        "screen-selection-background": "#7aa2f7",
        "screen-selection-foreground": "#1a1b26",
        # Canonical Pi-derived semantic roles (spec 72.a.5).
        "user-msg-bg": "#292e42",
        "tool-pending-bg": "#252a3d",
        "tool-success-bg": "#26342a",
        "tool-error-bg": "#3b2935",
        "thinking-text": "#9aa5ce",
        "md-heading": "#e0af68",
        "border-muted": "#565f89",
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
        # Authentication modal semantic roles (spec 78.a.3).
        "auth-surface": "#1f2335",
        "auth-border": "#565f89",
        "auth-heading": "#c0caf5",
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
