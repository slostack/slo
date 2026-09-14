"""Read what the Textual compositor actually painted, for authentication pilot tests.

The authentication defects were "instructions never appear" and "the URL is not a
link", which widget model state cannot prove. These helpers read the compositor's
painted strips instead. Shared by the screen, device E2E and authorization link tests
so one compositor-reading implementation exists.
"""

from __future__ import annotations

from rich.segment import Segment
from textual.app import App
from textual.geometry import Region
from textual.pilot import Pilot
from textual.strip import Strip
from textual.widget import Widget

_PAINT_ATTEMPTS: int = 100
_PAINT_ATTEMPT_DELAY_SECONDS: float = 0.05


def painted_widget_strips(*, app: App, widget: Widget) -> list[Strip]:
    """Return the painted rows inside one widget's on-screen region.

    WHO: Authorization link painting tests and the device E2E journey.
    WHEN: After a pilot pause, once the presentation has rendered.

    Args:
        app (App): Running harness app whose compositor is read.
        widget (Widget): Widget whose region is cropped out.

    Returns:
        list[Strip]: One cropped strip per painted row of the widget.
    """
    strips: list[Strip] = app.screen._compositor.render_strips()
    region: Region = widget.region
    return [strips[row].crop(start=region.x, end=region.right) for row in range(region.y, region.bottom)]


def painted_text(*, strips: list[Strip]) -> str:
    """Join painted cells without whitespace so wrapped text compares as one string.

    WHO: Painting assertions and ``wait_until_painted``.
    WHEN: After the strips were read from the compositor.

    Args:
        strips (list[Strip]): Painted rows to join.

    Returns:
        str: Whitespace-free painted text.
    """
    return "".join("".join(strip.text.split()) for strip in strips)


def painted_link_targets(*, strips: list[Strip]) -> set[str]:
    """Collect every OSC 8 hyperlink target carried by painted segments.

    WHO: Authorization link painting tests and the device E2E journey.
    WHEN: After the strips were read from the compositor.

    Args:
        strips (list[Strip]): Painted rows to inspect.

    Returns:
        set[str]: Link targets found on the painted segments.
    """
    segments: list[Segment] = [segment for strip in strips for segment in strip]
    return {segment.style.link for segment in segments if segment.style is not None and segment.style.link}


async def wait_until_painted(*, pilot: Pilot, text: str) -> str:
    """Pause until the viewport paints ``text`` (whitespace-insensitive) or a bounded wait lapses.

    WHO: Screen and device E2E tests whose presentation arrives from a background task.
    WHEN: After the pilot selected a sign-in method.

    Args:
        pilot (Pilot): Pilot driving the harness.
        text (str): Text expected on screen.

    Returns:
        str: The last whitespace-free painted viewport text, for the caller's assertion.
    """
    expected: str = "".join(text.split())
    painted: str = ""
    for _attempt in range(_PAINT_ATTEMPTS):
        await pilot.pause(_PAINT_ATTEMPT_DELAY_SECONDS)
        painted = painted_text(strips=pilot.app.screen._compositor.render_strips())
        if expected in painted:
            return painted
    return painted
