"""A1 test: the usage-bar plugin segment renders from the live dispatcher map.

The segment renders from a live dispatcher-owned status map that plugins
mutate via ``set_status`` at event time; load-time registration merely seeds
it. An event-time ``set_status`` updates the rendered segment.
"""

from __future__ import annotations

import pytest

from src.tui.widgets.usage_status_bar import UsageStatusBar


class _FakeDispatcher:
    """Minimal live-status-map owner mirroring ``PluginDispatcher``."""

    def __init__(self, *, seeded: dict[str, str]) -> None:
        """Seed the status map.

        Args:
            seeded (dict[str, str]): Load-time statuses.
        """
        self._map: dict[str, str] = dict(seeded)

    def status_map(self) -> dict[str, str]:
        """Return the live map.

        Returns:
            dict[str, str]: Current statuses.
        """
        return dict(self._map)

    def set_status(self, *, key: str, text: str) -> None:
        """Mutate one segment.

        Args:
            key (str): Segment key.
            text (str): Text; empty clears.
        """
        if text:
            self._map[key] = text
            return
        self._map.pop(key, None)


def test_plugin_segment_renders_seeded_statuses() -> None:
    """Load-time seeded statuses appear in the rendered line."""
    dispatcher = _FakeDispatcher(seeded={"ci-watch:status": "idle"})

    line: str = UsageStatusBar.render_plugin_segment(status_map=dispatcher.status_map())

    assert "ci-watch:status" in line or "idle" in line


def test_event_time_set_status_updates_rendered_segment() -> None:
    """A1: an event-time set_status changes what the bar renders."""
    dispatcher = _FakeDispatcher(seeded={"ci-watch:status": "idle"})
    before: str = UsageStatusBar.render_plugin_segment(status_map=dispatcher.status_map())

    dispatcher.set_status(key="ci-watch:status", text="tests running")
    after: str = UsageStatusBar.render_plugin_segment(status_map=dispatcher.status_map())

    assert "tests running" in after
    assert before != after


def test_plugin_segment_orders_multiple_statuses_by_stable_key() -> None:
    """Multiple plugin statuses render deterministically regardless of insertion order."""
    line: str = UsageStatusBar.render_plugin_segment(
        status_map={"zeta:status": "zeta", "alpha:status": "alpha"}
    )

    assert line == "alpha · zeta"


def test_empty_status_map_renders_empty_segment() -> None:
    """No plugin statuses means no segment text."""
    dispatcher = _FakeDispatcher(seeded={})

    assert UsageStatusBar.render_plugin_segment(status_map=dispatcher.status_map()) == ""


def test_cleared_status_leaves_segment() -> None:
    """Clearing a status removes it from the rendered segment."""
    dispatcher = _FakeDispatcher(seeded={"ci-watch:status": "idle"})
    dispatcher.set_status(key="ci-watch:status", text="")

    assert UsageStatusBar.render_plugin_segment(status_map=dispatcher.status_map()) == ""
