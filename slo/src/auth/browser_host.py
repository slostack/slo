"""Decide whether opening a browser is safe for a terminal UI process."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["BrowserHost"]

_GRAPHICAL_SESSION_VARIABLES: tuple[str, ...] = ("DISPLAY", "WAYLAND_DISPLAY", "BROWSER")
# Python's webbrowser registers these platforms' system browser ahead of any console browser.
# Every other platform (Linux, the BSDs, ...) falls back to console browsers when TERM is set.
_SYSTEM_BROWSER_PLATFORMS: frozenset[str] = frozenset({"darwin", "win32"})


@dataclass(frozen=True)
class BrowserHost:
    """The process environment and platform that decide whether a graphical browser can open."""

    environment: Mapping[str, str]
    platform: str

    @classmethod
    def current(cls) -> BrowserHost:
        """Describe the running process.

        WHO: OAuthFlow and SloTUI call this when no host is injected.
        WHEN: Once, while constructing the flow or the app.

        Returns:
            BrowserHost: A host reading the live ``os.environ`` and ``sys.platform``.
        """
        return cls(environment=os.environ, platform=sys.platform)

    def can_open_graphical_browser(self) -> bool:
        """Return whether a system browser, a graphical session, or an explicit BROWSER choice exists.

        WHAT: Without one, Python's ``webbrowser`` falls back to console browsers (www-browser,
            lynx, w3m) that wait for exit and draw on the TUI terminal, so the painted,
            clickable URL is the path instead. A host that passes can still run a console
            browser (``BROWSER=lynx``, or DISPLAY set with only console browsers installed);
            callers therefore also open off the event loop.
        WHO: OAuthFlow._attempt_browser_open and SloTUI.open_url call this.
        WHEN: Before every browser open attempt.

        Returns:
            bool: True on macOS and Windows, or when DISPLAY, WAYLAND_DISPLAY or BROWSER is set.
        """
        if self.platform in _SYSTEM_BROWSER_PLATFORMS:
            return True
        return any(self.environment.get(name) for name in _GRAPHICAL_SESSION_VARIABLES)
