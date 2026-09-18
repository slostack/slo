"""Import bridge for the exact on-disk 79_tui_v2 session fake fixture path."""

from __future__ import annotations

import importlib

BaselineSession = importlib.import_module("tests.fakes.79_tui_v2.session").BaselineSession

__all__ = ["BaselineSession"]
