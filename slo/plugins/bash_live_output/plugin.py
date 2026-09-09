"""Bundled general-purpose renderer for core Bash live output (Feature 75.a.5)."""

from __future__ import annotations

from typing import Any


_STATUS_KEY: str = "slo-slo:status"


def register(slo: Any) -> None:
    """Register consumer-only Bash live-output presentation extensions.

    WHAT: Observes core ``tool_output_update`` events and registers a raw-output
        renderer for Bash. It never spawns a process, reads a pipe, publishes an
        event, or alters model context.
    WHO: ``PluginLoader`` calls this factory when operators install the bundled
        plugin or developers explicitly dog-food it with ``--plugin``.
    WHEN: During session startup, after core streaming ownership is already wired.

    Args:
        slo (Any): Plugin API recorder supplied by the trusted loader.
    """
    slo.on(event_kind="tool_output_update", handler=_observe_bash_output_update)
    slo.register_tool_renderer(tool_name="bash", render=_render_bash_output)


def _observe_bash_output_update(event: Any) -> None:
    """Leave core output events untouched while remaining an observable subscriber.

    Args:
        event (Any): Core normalized stream event. The observer deliberately has
            no side effects so the bundled renderer remains consumer-only.
    """
    del event


def _render_bash_output(output: str) -> str:
    """Render any Bash snapshot as raw output without framework-specific parsing.

    Args:
        output (str): Accumulated core snapshot or terminal Bash result.

    Returns:
        str: The unchanged output so unrecognized command formats always render.
    """
    return output
