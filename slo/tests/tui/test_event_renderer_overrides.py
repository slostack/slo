"""Tests for the plugin renderer-override seam (75.a.5-PLUGIN).

``EventRenderer._summarize_tool_output`` consults the registered plugin
renderer map BEFORE the built-in ``_SUMMARIZERS``; when no override exists the
built-in fallback renders unchanged.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from src.tui.event_renderer import EventRenderer


@pytest.fixture(autouse=True)
def _clear_overrides() -> Generator[None, None, None]:
    """Reset the class-level override map around every test.

    Yields:
        None: Control returns after the test finishes.
    """
    EventRenderer.set_renderer_overrides(renderers={})
    yield
    EventRenderer.set_renderer_overrides(renderers={})


def test_plugin_renderer_wins_over_builtin_summarizer() -> None:
    """A registered override replaces the built-in bash summarizer."""
    EventRenderer.set_renderer_overrides(renderers={"bash": lambda output: f"LIVE: {output}"})

    summary: str = EventRenderer._summarize_tool_output(name="bash", output="raw output")

    assert summary == "LIVE: raw output"


def test_builtin_summarizer_used_when_no_override() -> None:
    """The built-in bash summary renders unchanged without an override."""
    summary: str = EventRenderer._summarize_tool_output(name="bash", output="line one\nline two")

    assert summary == "exit 0 · 2 lines"


def test_unknown_tool_falls_back_to_default_summary() -> None:
    """Tools with no override and no built-in hit the default summarizer."""
    summary: str = EventRenderer._summarize_tool_output(name="mystery", output="hello world")

    assert summary == "hello world"


def test_override_for_one_tool_leaves_others_untouched() -> None:
    """An override registered for ``bash`` does not affect ``read``."""
    EventRenderer.set_renderer_overrides(renderers={"bash": lambda output: "CUSTOM"})

    bash_summary: str = EventRenderer._summarize_tool_output(name="bash", output="x")
    read_summary: str = EventRenderer._summarize_tool_output(name="read", output="x")

    assert bash_summary == "CUSTOM"
    assert bash_summary != read_summary
