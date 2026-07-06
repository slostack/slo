"""Slo TUI themes.

Mirrors the design tokens used in the project homepage (finalized.html).

slo-default (tokyo-night palette — the primary theme):
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
    },
)
