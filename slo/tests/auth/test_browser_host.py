"""Tests for ``BrowserHost``, the one decision on whether a graphical browser can open."""

from __future__ import annotations

import os
import sys

import pytest

from src.auth.browser_host import BrowserHost


class TestBrowserHostCanOpenGraphicalBrowser:
    """Linux without a graphical session or BROWSER override is headless; other hosts are not."""

    def test_can_open_graphical_browser_when_linux_has_no_display_variables(self) -> None:
        """Linux with DISPLAY, WAYLAND_DISPLAY and BROWSER unset would fall back to console browsers."""
        host: BrowserHost = BrowserHost(environment={"TERM": "xterm-256color"}, platform="linux")

        assert host.can_open_graphical_browser() is False

    def test_can_open_graphical_browser_when_linux_display_variable_is_empty(self) -> None:
        """An empty variable is treated the same as an unset one."""
        host: BrowserHost = BrowserHost(environment={"DISPLAY": ""}, platform="linux")

        assert host.can_open_graphical_browser() is False

    @pytest.mark.parametrize("variable", ["DISPLAY", "WAYLAND_DISPLAY", "BROWSER"])
    def test_can_open_graphical_browser_when_linux_has_a_session_variable(self, variable: str) -> None:
        """Any one graphical session variable, or a BROWSER override, allows opening.

        Args:
            variable (str): The single environment variable set for this case.
        """
        host: BrowserHost = BrowserHost(environment={variable: ":0"}, platform="linux")

        assert host.can_open_graphical_browser() is True

    @pytest.mark.parametrize("platform", ["darwin", "win32"])
    def test_can_open_graphical_browser_when_platform_has_a_system_browser(self, platform: str) -> None:
        """macOS and Windows register their system browser ahead of console browsers.

        Args:
            platform (str): ``sys.platform`` value under test.
        """
        host: BrowserHost = BrowserHost(environment={}, platform=platform)

        assert host.can_open_graphical_browser() is True

    @pytest.mark.parametrize("platform", ["freebsd14", "openbsd7"])
    def test_can_open_graphical_browser_when_other_unix_has_no_display_variables(self, platform: str) -> None:
        """Other Unix platforms also fall back to console browsers when TERM is set.

        Args:
            platform (str): ``sys.platform`` value under test.
        """
        host: BrowserHost = BrowserHost(environment={"TERM": "xterm-256color"}, platform=platform)

        assert host.can_open_graphical_browser() is False

    def test_can_open_graphical_browser_when_other_unix_has_a_display(self) -> None:
        """A graphical session on another Unix platform allows opening."""
        host: BrowserHost = BrowserHost(environment={"DISPLAY": ":0"}, platform="freebsd14")

        assert host.can_open_graphical_browser() is True

    def test_current_reads_the_running_process(self) -> None:
        """``current()`` describes this process, so production callers need no wiring."""
        host: BrowserHost = BrowserHost.current()

        assert host.environment is os.environ
        assert host.platform == sys.platform
